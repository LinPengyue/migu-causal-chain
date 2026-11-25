"""Stage 1: external template -> evidence-grounded graph and candidate EDL.

No model calls, rendering, reference-chain access or first-live claims.
Native single-source input: delivery enriched events + predicted V1-adapter chains.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


def check(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def identifier(value):
    return isinstance(value, str) and bool(value.strip())


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_template(template):
    check(isinstance(template, dict), "template must be an object")
    for key in ("template_id", "category", "subtype", "goal"):
        check(identifier(template.get(key)), "missing template " + key)
    slots = template.get("slots")
    check(isinstance(slots, list) and bool(slots), "template requires ordered slots")
    seen = set()
    for slot in slots:
        sid = slot.get("slot_id")
        check(identifier(sid) and re.fullmatch(r"[a-z][a-z0-9_]*", sid), "invalid slot ID")
        check(sid not in seen, "duplicate slot: " + sid)
        seen.add(sid)
        check(identifier(slot.get("purpose")), "missing slot purpose: " + sid)
        lo, hi = slot.get("min_items"), slot.get("max_items")
        check(type(lo) is int and type(hi) is int and 0 <= lo <= hi and hi > 0,
              "invalid slot cardinality: " + sid)
        check(type(slot.get("anchor")) is bool, "explicit anchor flag required: " + sid)
    check(sum(s["min_items"] for s in slots) > 0, "at least one required material")
    return template


def flagged(value):
    return value is True or value == 1 or (isinstance(value, str) and value.lower() in {"true", "1"})


def known_nonlive(row):
    vc = row.get("video_context") or {}
    return (flagged(row.get("is_replay")) or flagged(vc.get("is_replay"))
            or flagged(vc.get("is_slow_motion")) or flagged(row.get("is_slow_motion"))
            or str(vc.get("broadcast_phase") or "").upper() in {"REPLAY", "SLOW_MOTION", "SLOWMO"})


def event_window(event, duration):
    mt = event.get("media_time") or {}
    t = mt.get("event_time_sec")
    if not number(t):
        t = next((event[k] for k in ("media_pts", "pts_sec", "t_sec") if number(event.get(k))), None)
    if not number(t) or not 0 <= t < duration:
        return None
    a, b = mt.get("start_time_sec"), mt.get("end_time_sec")
    basis = "annotated_media_window"
    if not number(a) or not number(b) or not a <= t < b:
        a, b = t - 2.0, t + 4.0
        basis = "event_anchor_preview_window"
    a, b = max(0.0, a), min(duration, b)
    if a >= b:
        return None
    return [a, b], t, basis


def make_inventory(events_doc, predicted, *, video_id, duration_sec):
    check(identifier(video_id) and number(duration_sec) and duration_sec > 0, "invalid source")
    events = events_doc if isinstance(events_doc, list) else events_doc.get("events")
    check(isinstance(events, list), "expected native enriched events list")
    check(isinstance(predicted, dict) and isinstance(predicted.get("v3_adapter"), dict)
          and isinstance(predicted.get("causal_chains"), list),
          "expected predicted V1-adapter causal document (not reference chains)")
    check(predicted.get("is_benchmark_gold") is not True, "benchmark gold not permitted")
    by_id, windows, materials, excluded = {}, {}, {}, []
    for e in events:
        eid = e.get("event_id")
        check(identifier(eid) and eid not in by_id, "missing or duplicate event_id")
        by_id[eid] = e
        windows[eid] = event_window(e, duration_sec)
    replay = [w[0] for eid, w in windows.items() if w is not None and known_nonlive(by_id[eid])]

    def overlaps_replay(a, b):
        return any(a < hi and b > lo for lo, hi in replay)

    for eid, e in by_id.items():
        w = windows[eid]
        if w is None or known_nonlive(e) or overlaps_replay(*w[0]):
            excluded.append({"material_id": "event:" + eid, "reason": "invalid_or_annotated_nonlive_window"})
            continue
        material_id = "event:" + eid
        materials[material_id] = {
            "material_id": material_id, "kind": "event", "event_ids": [eid],
            "window_sec": w[0], "window_basis": w[2], "video_id": video_id,
            "event_type": e.get("event_type") or e.get("event_type_zh"),
            "event_type_zh": e.get("event_type_zh"),
            "description": e.get("description") or e.get("event_description") or e.get("comment_label"),
            "teams": e.get("teams") or e.get("team"),
            "scores": e.get("scores"), "video_context": e.get("video_context"),
            "first_live_verified": False,
        }
    chain_seen = set()
    for ch in predicted["causal_chains"]:
        cid = ch.get("annotation_id")
        check(identifier(cid) and cid not in chain_seen, "missing or duplicate predicted chain ID")
        chain_seen.add(cid)
        mid = "chain:" + cid
        check(ch.get("is_benchmark_gold") is not True, "benchmark gold chain not permitted")
        ids = list(dict.fromkeys(e.get("event_id") for e in ch.get("events") or []))
        if not ids or known_nonlive(ch) or any("event:" + str(i) not in materials for i in ids):
            excluded.append({"material_id": mid, "reason": "unbound_or_nonlive_chain"})
            continue
        a = min(materials["event:" + i]["window_sec"][0] for i in ids)
        b = max(materials["event:" + i]["window_sec"][1] for i in ids)
        if overlaps_replay(a, b):
            excluded.append({"material_id": mid, "reason": "chain_window_overlaps_annotated_replay"})
            continue
        materials[mid] = {
            "material_id": mid, "kind": "predicted_chain", "event_ids": ids,
            "predicted_chain_id": cid, "video_id": video_id, "window_sec": [a, b],
            "window_basis": "envelope_of_bound_event_windows",
            "category": ch.get("chain_category"), "subtype": ch.get("causal_chain_subtype"),
            "first_live_verified": False,
        }
    return {"video_id": video_id, "duration_sec": duration_sec,
            "materials": materials, "excluded": excluded}


def planner_request(template, inventory):
    validate_template(template)
    return {
        "template": template,
        "materials": sorted(inventory["materials"].values(),
                            key=lambda x: (x["window_sec"][0], x["material_id"])),
        "instruction": (
            "Given the supplied story template, select actual event or predicted-chain material IDs "
            "for each slot. Use chronological, non-overlapping source windows; do not repeat events. "
            "Respect protagonist/team evidence, choose only relevant material, and leave unsupported "
            "slots empty rather than inventing content. Slots may have several materials. "
            "Do not generate times, assert causal proof, or infer first-live from metadata. "
            "Return only JSON: {bindings:[{slot_id,material_ids:[...]}]}. "
            "Selection is a narrative hypothesis for subsequent video review."
        ),
    }


def instantiate(template, inventory, selection):
    """Bind IDs only; model-generated PTS and causal claims are not executable."""
    validate_template(template)
    check(isinstance(selection, dict) and set(selection) == {"bindings"}, "unexpected planner fields")
    check(isinstance(selection["bindings"], list), "bindings must be a list")
    slots = {s["slot_id"]: s for s in template["slots"]}
    bindings = {}
    for row in selection["bindings"]:
        check(isinstance(row, dict) and set(row) == {"slot_id", "material_ids"}, "unexpected binding fields")
        sid = row["slot_id"]
        check(sid in slots and sid not in bindings, "unknown or duplicate slot")
        ids = row["material_ids"]
        check(isinstance(ids, list) and all(identifier(x) for x in ids), "invalid material IDs")
        check(len(ids) <= slots[sid]["max_items"], "slot exceeds maximum: " + sid)
        bindings[sid] = ids
    edl, missing, nodes, edges = [], [], [], []
    used_events, previous_end = set(), 0.0
    materials = inventory["materials"]
    for slot in template["slots"]:
        sid = slot["slot_id"]
        ids = bindings.get(sid, [])
        if len(ids) < slot["min_items"]:
            missing.append({"slot_id": sid, "required": slot["min_items"], "selected": len(ids)})
        for index, mid in enumerate(ids, 1):
            check(mid in materials, "unknown material: " + mid)
            m = materials[mid]
            a, b = m["window_sec"]
            eids = set(m["event_ids"])
            check(not used_events.intersection(eids), "duplicate event across slots: " + mid)
            check(a >= previous_end, "overlapping or nonchronological source windows: " + mid)
            previous_end = b
            used_events.update(eids)
            nid = f"{sid}:{index}"
            seg = "seg_template_" + sid + "_" + str(index)
            row = {
                "segment_id": seg, "template_slot_id": sid, "beat": sid, "role": sid,
                "story_anchor": slot["anchor"], "video_id": inventory["video_id"],
                "media_in": a, "media_out": b, "event_ids": list(m["event_ids"]),
                "short_chain_ids": [m["predicted_chain_id"]] if m["kind"] == "predicted_chain" else [],
                "source_material_id": mid, "time_provenance": {"basis": m["window_basis"]},
                "include_in_cut": True, "narrative_order": len(edl) + 1,
                "edl_index": len(edl) + 1, "shot_kind": "action",
                "verification_status": "draft", "first_live_status": "NOT_VERIFIED",
                "first_live_verified": False, "preview_only": True,
            }
            edl.append(row)
            nodes.append({"node_id": nid, "slot_id": sid, "segment_id": seg,
                          "material_id": mid, "event_ids": row["event_ids"],
                          "short_chain_ids": row["short_chain_ids"],
                          "source_window_sec": [a, b], "semantic_status": "UNREVIEWED"})
            if len(nodes) > 1:
                edges.append({"from": nodes[-2]["node_id"], "to": nid,
                              "relation": "editorial_precedes", "causal_verified": False})
    template_graph = {
        "nodes": template["slots"],
        "edges": [{"from": a["slot_id"], "to": b["slot_id"], "relation": "editorial_precedes"}
                  for a, b in zip(template["slots"], template["slots"][1:])],
    }
    return {
        "template_id": template["template_id"], "category": template["category"],
        "subtype": template["subtype"], "story_goal": template["goal"],
        "template_graph": template_graph, "story_graph": {"nodes": nodes, "edges": edges},
        "candidate_edl": edl, "missing_required_slots": missing,
        "structurally_complete": not missing,
        "preview_only": True, "release_authorized": False,
        "quality_verified": False, "first_live_verified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--template", required=True)
    p.add_argument("--events", required=True)
    p.add_argument("--predicted-causal", required=True)
    p.add_argument("--video-id", required=True)
    p.add_argument("--duration-sec", required=True, type=float)
    p.add_argument("--selection", help="Optional planner response JSON; omit to prepare request only")
    p.add_argument("--out-dir", required=True)
    a = p.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=False)
    template = read(a.template)
    inventory = make_inventory(read(a.events), read(a.predicted_causal),
                               video_id=a.video_id, duration_sec=a.duration_sec)
    write(out / "inventory.json", inventory)
    write(out / "planner_request.json", planner_request(template, inventory))
    if a.selection:
        result = instantiate(template, inventory, read(a.selection))
        write(out / "story_graph_bundle.json", result)
        write(out / "candidate_edl.json", result["candidate_edl"])


if __name__ == "__main__":
    main()
