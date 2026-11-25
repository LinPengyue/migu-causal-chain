"""Stage 1.2: compact evidence representation and event-bound story instances.

Separate predicted-chain context from executable media. No API or rendering.
Use delivery-native event documents; benchmark adapters are future work.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from template_graph import check, identifier, number, known_nonlive, event_window, validate_template, read, write


def input_tier(events, report, allow_dev=False):
    check(isinstance(report, dict) and report, "enrichment report required")
    provenance = [(e.get("enrichment") or {}).get("provenance") for e in events]
    legacy = bool(report.get("source_causal_atoms_only")) or "causal_atom_fill" in provenance
    independent = bool(report.get("source_independent_atoms")) or "independent_atomic_annotation" in provenance
    declared = report.get("input_mode")
    if legacy or declared == "HUMAN_ATOM_ENRICHED_DEV":
        tier = "HUMAN_ATOM_ENRICHED_DEV"
    elif independent and declared == "INDEPENDENT_ATOMIC_ANNOTATED" and report.get("independent_atomic_annotations_used") is True:
        tier = declared
    elif declared == "RAW_EVENTS_ONLY" and not independent and report.get("eligible_for_raw_only_evaluation") is True:
        tier = declared
    else:
        tier = "UNCONFIRMED_PROVENANCE_DEV"
    check(allow_dev or tier in {"RAW_EVENTS_ONLY", "INDEPENDENT_ATOMIC_ANNOTATED"},
          "development or unconfirmed input requires --allow-dev")
    return tier


def build_evidence(events_doc, predicted, report, *, video_id, duration_sec, allow_dev=False):
    check(identifier(video_id) and number(duration_sec) and duration_sec > 0, "invalid source")
    check(isinstance(events_doc, dict) and isinstance(events_doc.get("events"), list),
          "native event object required")
    events = events_doc["events"]
    check(isinstance(predicted, dict) and isinstance(predicted.get("v3_adapter"), dict)
          and isinstance(predicted.get("causal_chains"), list)
          and predicted.get("is_benchmark_gold") is not True, "predicted V1-adapter document required")
    tier = input_tier(events, report, allow_dev)
    by_id, windows, atoms, excluded = {}, {}, {}, {}
    for e in events:
        eid = e.get("event_id")
        check(identifier(eid) and eid not in by_id, "missing or duplicate event id")
        by_id[eid] = e
        windows[eid] = event_window(e, duration_sec)
    replay = [w[0] for eid,w in windows.items() if w and known_nonlive(by_id[eid])]
    for eid,e in by_id.items():
        w = windows[eid]
        if known_nonlive(e):
            excluded[eid] = "annotated_nonlive"
        elif not w:
            excluded[eid] = "invalid_window"
        elif any(w[0][0] < b and w[0][1] > a for a,b in replay):
            excluded[eid] = "overlaps_annotated_nonlive"
        else:
            vc = e.get("video_context") or {}
            atoms[eid] = {
                "event_id": eid, "window": w[0], "t": w[1], "window_basis": w[2],
                "type": e.get("event_type"), "type_zh": e.get("event_type_zh"),
                "label": e.get("comment_label"), "notes": e.get("notes"),
                "description": e.get("description") or e.get("event_description"),
                "attributes": e.get("attributes"), "scores": e.get("scores"),
                "teams": e.get("teams") or e.get("team"),
                "broadcast_phase": vc.get("broadcast_phase"),
                "enrichment_provenance": (e.get("enrichment") or {}).get("provenance"),
            }
    chains = {}
    for c in predicted["causal_chains"]:
        cid = c.get("annotation_id")
        check(identifier(cid) and cid not in chains and c.get("is_benchmark_gold") is not True,
              "invalid predicted chain")
        ids = list(dict.fromkeys(e.get("event_id") for e in c.get("events") or []))
        valid = [i for i in ids if i in atoms]
        unavailable = [{"event_id": i, "reason": excluded.get(i, "unbound")} for i in ids if i not in atoms]
        state = ("NONLIVE_CHAIN" if known_nonlive(c) else "FULL" if ids and not unavailable
                 else "PARTIAL" if valid else "UNAVAILABLE")
        chains[cid] = {"chain_id": cid, "category": c.get("chain_category"),
                       "subtype": c.get("causal_chain_subtype"), "event_ids": ids,
                       "available_event_ids": valid, "unavailable": unavailable,
                       "state": state, "causal_verified": False}
    return {"schema": "sportscausal_evidence_v2", "video_id": video_id,
            "duration_sec": duration_sec, "teams": events_doc.get("teams"),
            "input_tier": tier, "atoms": atoms, "chains": chains,
            "excluded_events": excluded, "first_live_verified": False,
            "lineage_limit": "Report and event provenance checked; upstream prediction run linkage requires external run manifest."}


def compact_request(template, evidence):
    validate_template(template)
    # Common fields appear once. Attribute values and notes are not truncated.
    # Keep every eligible event. A missing value is represented by omission.
    columns = ["event_id","t","window","type","type_zh","label","notes","description",
               "attributes","scores","teams","broadcast_phase","enrichment_provenance","window_basis"]
    rows = [[a.get(k) for k in columns] for a in sorted(evidence["atoms"].values(),
                                                         key=lambda a:(a["t"],a["event_id"]))]
    chain_rows = [[c["chain_id"],c["category"],c["subtype"],c["state"],
                   c["available_event_ids"],len(c["unavailable"])]
                  for c in evidence["chains"].values() if c["state"] in {"FULL","PARTIAL"}]
    return {
        "template": template,
        "source": {"video_id": evidence["video_id"], "duration_sec": evidence["duration_sec"],
                   "teams": evidence["teams"], "input_tier": evidence["input_tier"]},
        "event_columns": columns, "events": rows,
        "chain_columns": ["chain_id","category","subtype","availability","available_event_ids","n_unavailable"],
        "predicted_chains": chain_rows,
        "instruction": (
            "Build a story conditioned on the supplied template. Read notes and role-specific "
            "attributes, including team-side mappings; nearby events alone do not establish identity. "
            "FULL means all member IDs are available, not that the predicted causal relation is true. "
            "PARTIAL is context only; do not infer missing events or complete causal outcomes. "
            "Use events as media evidence and optionally cite predicted chain IDs as context. "
            "Group related events into one slot instance; select only necessary footage. "
            "No event reuse between instances, no invented times or identity. "
            "Return only JSON {bindings:[{slot_id,instances:[{event_ids:[...],chain_ids:[...]}]}]}. "
            "Leave unsupported slots empty. All selections require subsequent semantic video review."
        ),
    }


def _merge_windows(atoms):
    # Union overlaps within an instance, never fill gaps between separate actions.
    groups = []
    for a in sorted(atoms, key=lambda x:(x["window"][0], x["window"][1], x["event_id"])):
        lo,hi = a["window"]
        if groups and lo <= groups[-1][1]:
            g = groups[-1]
            g[1] = max(g[1],hi)
            g[2].append(a["event_id"])
        else:
            groups.append([lo,hi,[a["event_id"]]])
    return groups


def bind_story(template, evidence, selection):
    validate_template(template)
    check(isinstance(selection,dict) and set(selection)=={"bindings"} and isinstance(selection["bindings"],list),
          "invalid selection")
    slots = {s["slot_id"]:s for s in template["slots"]}
    by_slot = {}
    for b in selection["bindings"]:
        check(isinstance(b,dict) and set(b)=={"slot_id","instances"}, "invalid binding")
        sid = b["slot_id"]
        check(sid in slots and sid not in by_slot and isinstance(b["instances"],list), "invalid slot")
        check(len(b["instances"]) <= slots[sid]["max_items"], "too many instances")
        by_slot[sid] = b["instances"]
    nodes, edges, edl, missing, used = [], [], [], [], set()
    end = 0.0
    for sid,s in slots.items():
        instances = by_slot.get(sid,[])
        if len(instances) < s["min_items"]:
            missing.append({"slot_id":sid,"required":s["min_items"],"selected":len(instances)})
        for i,item in enumerate(instances,1):
            check(isinstance(item,dict) and set(item)=={"event_ids","chain_ids"}, "invalid instance")
            ids,cids = item["event_ids"],item["chain_ids"]
            check(isinstance(ids,list) and bool(ids) and all(identifier(x) for x in ids)
                  and len(ids)==len(set(ids)), "invalid event selection")
            check(isinstance(cids,list) and all(identifier(x) for x in cids)
                  and len(cids)==len(set(cids)), "invalid chain references")
            check(all(e in evidence["atoms"] for e in ids) and not used.intersection(ids), "unknown or reused event")
            for cid in cids:
                c = evidence["chains"].get(cid)
                check(c and c["state"] in {"FULL","PARTIAL"}
                      and set(ids).intersection(c["available_event_ids"]), "unbound chain context")
            used.update(ids)
            windows = _merge_windows([evidence["atoms"][e] for e in ids])
            nid = f"{sid}:{i}"
            segs = []
            for j,(lo,hi,eids) in enumerate(windows,1):
                check(lo >= end, "overlap or nonchronological story instances")
                end = hi
                seg = f"seg_template_{sid}_{i}_{j}"
                segs.append(seg)
                refs = [c for c in cids if set(eids).intersection(evidence["chains"][c]["available_event_ids"])]
                edl.append({"segment_id":seg, "template_slot_id":sid, "story_node_id":nid,
                            "role":sid, "beat":sid, "story_anchor":s["anchor"] and j==len(windows),
                            "video_id":evidence["video_id"], "media_in":lo,"media_out":hi,
                            "event_ids":eids,"short_chain_ids":refs,
                            "include_in_cut":True, "edl_index":len(edl)+1,
                            "narrative_order":len(edl)+1, "shot_kind":"action",
                            "time_provenance":{"basis":"union_of_selected_atomic_windows"},
                            "first_live_status":"NOT_VERIFIED","verification_status":"draft",
                            "preview_only":True})
            nodes.append({"node_id":nid,"slot_id":sid,"event_ids":ids,"chain_ids":cids,
                          "segment_ids":segs,"semantic_status":"UNREVIEWED"})
            if len(nodes)>1:
                edges.append({"from":nodes[-2]["node_id"],"to":nid,"relation":"editorial_precedes",
                              "causal_verified":False})
    return {"template_id":template["template_id"],"category":template["category"],
            "subtype":template["subtype"],"story_goal":template["goal"],
            "story_graph":{"nodes":nodes,"edges":edges},"candidate_edl":edl,
            "missing_required_slots":missing,"structurally_complete":not missing,
            "input_tier":evidence["input_tier"],"preview_only":True,
            "release_authorized":False,"quality_verified":False,"first_live_verified":False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("template","events","predicted-causal","enrich-report","video-id","out-dir"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--duration-sec",type=float,required=True)
    p.add_argument("--allow-dev",action="store_true")
    p.add_argument("--selection")
    a = p.parse_args()
    template = read(a.template)
    e = build_evidence(read(a.events),read(a.predicted_causal),read(a.enrich_report),
                       video_id=a.video_id,duration_sec=a.duration_sec,allow_dev=a.allow_dev)
    out = Path(a.out_dir)
    out.mkdir(parents=True,exist_ok=False)
    write(out/"evidence.json",e)
    write(out/"planner_request.json",compact_request(template,e))
    if a.selection:
        r = bind_story(template,e,read(a.selection))
        write(out/"story_graph_bundle.json",r)
        write(out/"candidate_edl.json",r["candidate_edl"])


if __name__ == "__main__":
    main()
