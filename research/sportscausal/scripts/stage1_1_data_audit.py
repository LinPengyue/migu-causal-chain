#!/usr/bin/env python3
"""Stage 1.1 zero-cost data audit for SportsCausal template preflight inputs.

No model calls. Reads existing raw/enriched/predicted artifacts only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from template_graph import event_window, known_nonlive  # noqa: E402


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def flatten_keys(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(flatten_keys(v, p))
            else:
                out[p] = v
    return out


def nonempty_attr_paths(events):
    counts = Counter()
    for e in events:
        flat = flatten_keys({
            "event_type": e.get("event_type"),
            "event_type_zh": e.get("event_type_zh"),
            "comment_label": e.get("comment_label"),
            "attributes": e.get("attributes") or {},
            "scores": e.get("scores") or {},
            "video_context": e.get("video_context") or {},
            "enrichment": e.get("enrichment") or {},
            "notes": e.get("notes"),
        })
        for k in (
            "team", "teams", "team_id", "team_name", "player", "player_name",
            "jersey", "shirt_color", "subject", "actor", "possession_team",
        ):
            if k in e:
                flat[k] = e.get(k)
        for k, v in flat.items():
            if v not in (None, "", [], {}, False):
                counts[k] += 1
    return counts


def pick_examples(events, typenames, n=2):
    wanted = {t.lower() for t in typenames}
    found = []
    for e in events:
        et = str(e.get("event_type") or "").lower()
        ez = str(e.get("event_type_zh") or "").lower()
        if et in wanted or ez in wanted or any(t in et or t in ez for t in wanted):
            found.append(e)
            if len(found) >= n:
                break
    return found


def slim_event(e):
    return {
        "event_id": e.get("event_id"),
        "event_type": e.get("event_type"),
        "event_type_zh": e.get("event_type_zh"),
        "event_type_id": e.get("event_type_id"),
        "comment_label": e.get("comment_label"),
        "media_time": e.get("media_time"),
        "attributes": e.get("attributes"),
        "scores": e.get("scores"),
        "video_context": e.get("video_context"),
        "enrichment": e.get("enrichment"),
        "notes": e.get("notes"),
        "top_level_extra": {
            k: e.get(k) for k in e.keys()
            if k not in {
                "event_id", "event_type", "event_type_zh", "event_type_id",
                "comment_label", "bz_id", "is_model_target", "media_time",
                "attributes", "video_context", "scores", "annotation_quality",
                "notes", "enrichment",
            } and e.get(k) not in (None, "", [], {})
        },
    }


def provenance_audit(match_id, enrich_report, raw, causal, enriched):
    atoms_from_chains = 0
    chain_fields_seen = Counter()
    for ch in causal.get("causal_chains") or []:
        for k in (
            "chain_category", "causal_chain_subtype", "segment_time_video",
            "segment_time_sketch", "is_replay", "events",
        ):
            if ch.get(k) not in (None, "", [], {}):
                chain_fields_seen[k] += 1
        atoms_from_chains += len(ch.get("events") or [])
    enriched_events = enriched.get("events") or []
    atom_fill = [
        e for e in enriched_events
        if str(e.get("event_id", "")).startswith("atom_fill_")
        or (e.get("enrichment") or {}).get("provenance") == "causal_atom_fill"
    ]
    raw_ids = {e.get("event_id") for e in (raw.get("events") or [])}
    return {
        "match_id": match_id,
        "enrich_report": enrich_report,
        "conclusion": {
            "atom_fill_source": "historical_human_causal_chains_flattened",
            "not_independent_atomic_annotations": True,
            "evidence": [
                "enrich_report.source_causal_atoms_only points at *_causal.json containing causal_chains[]",
                "atomic_event_enrich.extract_atomic_events flattens causal_chains events by (type_en,t_ms)",
                "injected events carry enrichment.provenance=causal_atom_fill",
                "independent path enrich_with_independent_atoms exists but was NOT used for A/B",
            ],
            "what_was_stripped_on_inject": [
                "chain_category", "causal_chain_subtype", "segment_time_video", "edges", "story roles",
            ],
            "human_causal_file_still_has_chain_labels": True,
            "n_human_causal_chains": len(causal.get("causal_chains") or []),
            "n_event_mentions_inside_human_chains": atoms_from_chains,
            "human_chain_fields_nonempty_counts": dict(chain_fields_seen),
            "n_atom_fill_in_enriched": len(atom_fill),
            "n_raw_events": len(raw.get("events") or []),
            "n_enriched_events": len(enriched_events),
            "atom_fill_ids_sample": [e.get("event_id") for e in atom_fill[:8]],
            "raw_ids_disjoint_from_atom_fill": all(e.get("event_id") not in raw_ids for e in atom_fill),
        },
    }


def char_cost_breakdown(planner_request):
    template = planner_request["template"]
    materials = planner_request["materials"]
    instruction = planner_request["instruction"]

    def dumps(x):
        return json.dumps(x, ensure_ascii=False, separators=(",", ":"))

    total = dumps(planner_request)
    field_chars = Counter()
    for m in materials:
        for k, v in m.items():
            field_chars[k] += len(dumps(v))
    rows = [
        {
            "scope": "materials_field_sum",
            "field": k,
            "chars": c,
            "share_of_materials": round(c / max(1, sum(field_chars.values())), 4),
        }
        for k, c in field_chars.most_common()
    ]
    compressible = []
    often_null = []
    for k in field_chars:
        nullish = sum(1 for m in materials if m.get(k) in (None, "", [], {}, False))
        frac = nullish / max(1, len(materials))
        if frac >= 0.9:
            often_null.append({"field": k, "nullish_fraction": round(frac, 4), "chars": field_chars[k]})
    if field_chars.get("video_id"):
        compressible.append({
            "idea": "hoist video_id to request root once",
            "chars_saved_estimate": field_chars["video_id"] - len(dumps(materials[0].get("video_id"))),
            "lossless": True,
        })
    if field_chars.get("first_live_verified"):
        compressible.append({
            "idea": "omit constant-false field materials[].first_live_verified (document default=false)",
            "chars_saved_estimate": field_chars["first_live_verified"],
            "lossless": True,
        })
    for row in often_null:
        if row["field"] != "first_live_verified":
            compressible.append({
                "idea": f"omit mostly-empty field materials[].{row['field']}",
                "chars_saved_estimate": row["chars"],
                "nullish_fraction": row["nullish_fraction"],
                "lossless": True,
            })
    equal_desc = sum(
        1 for m in materials
        if m.get("kind") == "event" and m.get("description") in {
            m.get("event_type"), m.get("event_type_zh"), m.get("comment_label"), None, "",
        }
    )
    if field_chars.get("description"):
        compressible.append({
            "idea": "drop description when equal to event_type/event_type_zh/comment_label/empty",
            "equal_or_empty_event_materials": equal_desc,
            "chars_saved_estimate": "up_to_description_field_sum_for_those_rows",
            "lossless": True,
        })
    return {
        "total_chars": len(total),
        "template_chars": len(dumps(template)),
        "instruction_chars": len(dumps(instruction)),
        "materials_chars": len(dumps(materials)),
        "n_materials": len(materials),
        "materials_field_char_costs": rows,
        "equal_description_to_type_or_empty": equal_desc,
        "lossless_compression_candidates": compressible,
    }


def audit_chains(match_label, predicted, enriched, inventory, duration):
    by_id = {e["event_id"]: e for e in (enriched.get("events") or [])}
    mats = inventory["materials"]
    excl = {x["material_id"]: x["reason"] for x in inventory["excluded"]}
    rows = []
    for ch in predicted.get("causal_chains") or []:
        cid = ch.get("annotation_id")
        mid = "chain:" + str(cid)
        eids = [e.get("event_id") for e in (ch.get("events") or []) if e.get("event_id")]
        times = []
        n_valid = n_replay = n_unbound = 0
        per_event = []
        for eid in eids:
            e = by_id.get(eid)
            st = {"event_id": eid}
            if e is None:
                n_unbound += 1
                st["status"] = "unbound_missing_from_enriched"
            else:
                w = event_window(e, duration)
                nonlive = known_nonlive(e)
                st["is_replay_or_slowmo"] = nonlive
                st["in_event_materials"] = ("event:" + eid) in mats
                if w:
                    times.extend(w[0])
                    st["window_sec"] = w[0]
                if nonlive:
                    n_replay += 1
                    st["status"] = "nonlive"
                elif w and ("event:" + eid) in mats:
                    n_valid += 1
                    st["status"] = "valid"
                elif not w:
                    n_unbound += 1
                    st["status"] = "invalid_window"
                else:
                    n_unbound += 1
                    st["status"] = "not_in_materials"
            per_event.append(st)
        span = [min(times), max(times)] if times else None
        in_inv = mid in mats
        reason = None if in_inv else excl.get(mid, "not_listed_in_excluded_unexpected")
        if in_inv:
            usability = "fully_available_in_inventory"
        elif n_valid > 0 and (n_replay > 0 or n_unbound > 0):
            usability = "partial_evidence_unusable_as_chain"
        elif n_valid == 0:
            usability = "fully_unusable_as_chain"
        else:
            usability = "unknown"
        rows.append({
            "match": match_label,
            "predicted_chain_id": cid,
            "material_id": mid,
            "raw_chain_category": ch.get("chain_category") or ch.get("category"),
            "raw_chain_subtype": ch.get("causal_chain_subtype") or ch.get("subtype"),
            "predicted_is_benchmark_gold": ch.get("is_benchmark_gold"),
            "n_events_in_chain": len(eids),
            "time_span_sec": span,
            "time_span_duration_sec": None if not span else round(span[1] - span[0], 3),
            "n_valid_atomic_events_in_inventory": n_valid,
            "n_replay_or_slowmo_events": n_replay,
            "n_unbound_or_invalid_events": n_unbound,
            "in_inventory": in_inv,
            "inventory_exclusion_reason": reason,
            "usability": usability,
            "event_statuses": per_event,
        })
    summary = {
        "n_chains": len(rows),
        "fully_available": sum(1 for r in rows if r["usability"] == "fully_available_in_inventory"),
        "partial_evidence_unusable_as_chain": sum(
            1 for r in rows if r["usability"] == "partial_evidence_unusable_as_chain"
        ),
        "fully_unusable_as_chain": sum(1 for r in rows if r["usability"] == "fully_unusable_as_chain"),
        "exclusion_reason_counts": dict(
            Counter(r["inventory_exclusion_reason"] for r in rows if not r["in_inventory"])
        ),
        "category_counts": dict(Counter(r["raw_chain_category"] for r in rows)),
        "subtype_counts": dict(Counter(r["raw_chain_subtype"] for r in rows)),
    }
    return rows, summary


def save_neighborhood(enriched, n_examples=5, neighbor=3):
    events = enriched.get("events") or []

    def t_of(e):
        return (e.get("media_time") or {}).get("event_time_sec")

    ordered = sorted([e for e in events if t_of(e) is not None], key=t_of)
    saves = [
        e for e in ordered
        if str(e.get("event_type") or "").lower() == "save"
        or str(e.get("event_type_zh") or "") in {"扑救", "Save"}
    ]
    live_saves = [e for e in saves if not known_nonlive(e)] or saves
    out = []
    for s in live_saves[:n_examples]:
        idx = ordered.index(s)
        window = ordered[max(0, idx - neighbor): idx + neighbor + 1]
        seq = []
        for e in window:
            attrs = e.get("attributes") or {}
            seq.append({
                "event_id": e.get("event_id"),
                "event_type": e.get("event_type"),
                "event_type_zh": e.get("event_type_zh"),
                "t_sec": t_of(e),
                "is_replay_or_slowmo": known_nonlive(e),
                "attributes": attrs,
                "scores": e.get("scores") or {},
                "video_context": e.get("video_context") or {},
                "enrichment_provenance": (e.get("enrichment") or {}).get("provenance"),
                "team_like_fields": {
                    k: e.get(k) for k in e
                    if any(x in k.lower() for x in (
                        "team", "player", "jersey", "shirt", "color", "subject", "actor", "possess",
                    ))
                },
                "attribute_team_like": {
                    k: v for k, v in attrs.items()
                    if any(x in str(k).lower() for x in (
                        "team", "player", "jersey", "shirt", "color", "subject", "actor", "possess", "side",
                    ))
                },
            })
        center = next(x for x in seq if x["event_id"] == s.get("event_id"))
        can_team_center = bool(center["team_like_fields"] or center["attribute_team_like"])
        neighbor_team_hits = [
            {
                "event_id": x["event_id"],
                "event_type": x["event_type"],
                "attribute_team_like": x["attribute_team_like"],
            }
            for x in seq
            if x["attribute_team_like"] or x["team_like_fields"]
        ]
        out.append({
            "save_event_id": s.get("event_id"),
            "save_t_sec": t_of(s),
            "neighborhood": seq,
            "team_attribution_from_save_event_fields": can_team_center,
            "team_attribution_from_neighborhood_attributes": bool(neighbor_team_hits),
            "neighborhood_team_attribute_hits": neighbor_team_hits,
            "note": (
                "Save centers often lack BallController_team; adjacent Pass/duel rows may carry "
                "BallController_team / Related_Player. Match header still holds jersey colors."
            ),
        })
    return {
        "n_save_events_total": len(saves),
        "n_live_save_events": sum(1 for e in saves if not known_nonlive(e)),
        "examples": out,
    }


def main():
    out = Path(sys.argv[1])
    matches = {
        "A_uae_oman": {
            "raw": "/data2/lpy1/causal-chain2/11.23casual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json",
            "causal_human": "/data2/lpy1/causal-chain2/11.23casual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语_causal.json",
            "enriched": "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/01_enrich/events_enriched.json",
            "enrich_report": "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/01_enrich/enrich_report.json",
            "predicted": "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/03_v1_adapt/predicted_causal.json",
            "planner_request": str(ROOT / "artifacts/stage1_preflight_20261125/A_uae_oman/keeper_rescue/planner_request.json"),
            "inventory": str(ROOT / "artifacts/stage1_preflight_20261125/A_uae_oman/keeper_rescue/inventory.json"),
            "video_id": "10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语",
            "duration_sec": 8149.48,
            "source_mp4": "/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4",
        },
        "B_osasuna_celta": {
            "raw": "/data2/lpy1/causal-chain2/11.23casual_chain/data/交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json",
            "causal_human": "/data2/lpy1/causal-chain2/11.23casual_chain/data/交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语_causal.json",
            "enriched": "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/01_enrich/events_enriched.json",
            "enrich_report": "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/01_enrich/enrich_report.json",
            "predicted": "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/03_v1_adapt/predicted_causal.json",
            "planner_request": str(ROOT / "artifacts/stage1_preflight_20261125/B_osasuna_celta/keeper_rescue/planner_request.json"),
            "inventory": str(ROOT / "artifacts/stage1_preflight_20261125/B_osasuna_celta/keeper_rescue/inventory.json"),
            "video_id": "10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语",
            "duration_sec": 7676.061,
            "source_mp4": "/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4",
        },
    }

    summary = {"schema": "sportscausal_stage1_1_data_audit_v1", "paid_api": False, "matches": {}}
    for label, cfg in matches.items():
        raw, causal, enriched = load(cfg["raw"]), load(cfg["causal_human"]), load(cfg["enriched"])
        report = load(cfg["enrich_report"])
        predicted = load(cfg["predicted"])
        inventory = load(cfg["inventory"])
        planner = load(cfg["planner_request"])

        prov = provenance_audit(label, report, raw, causal, enriched)
        write(out / f"provenance_{label}.json", prov)

        teams = raw.get("teams") or {}
        raw_events = raw.get("events") or []
        counts = nonempty_attr_paths(raw_events)
        samples = {}
        for name, aliases in [
            ("Save", ["save", "扑救"]),
            ("Shot", ["shot", "射门"]),
            ("Corner_kick", ["corner_kick", "corner", "角球"]),
            ("Goal", ["goal", "进球"]),
            ("Defensive_action", ["defensive_action", "防守动作", "防守"]),
        ]:
            ex = pick_examples(raw_events, aliases, n=2)
            if not ex:
                ex = pick_examples(enriched.get("events") or [], aliases, n=2)
            samples[name] = [slim_event(e) for e in ex]

        attr_keys = Counter()
        for e in raw_events:
            for k, v in (e.get("attributes") or {}).items():
                if v not in (None, "", [], {}):
                    attr_keys[k] += 1

        field_report = {
            "match": label,
            "raw_teams_header": teams,
            "human_causal_team_colors": {
                "team_1_name": causal.get("team_1_name"),
                "team_2_name": causal.get("team_2_name"),
                "team_1_color": causal.get("team_1_color"),
                "team_2_color": causal.get("team_2_color"),
            },
            "nonempty_field_counts_on_raw_events": dict(counts.most_common(80)),
            "attributes_nonempty_key_counts": dict(attr_keys.most_common(80)),
            "has_player_fields_on_events": any("player" in k.lower() for k in list(counts) + list(attr_keys)),
            "has_team_fields_on_events": any("team" in k.lower() for k in list(counts) + list(attr_keys)),
            "has_jersey_or_color_on_events": any(
                any(x in k.lower() for x in ("jersey", "shirt", "color", "kit"))
                for k in list(counts) + list(attr_keys)
            ),
            "examples": samples,
        }
        write(out / "samples" / f"event_fields_{label}.json", field_report)

        rows, chain_summary = audit_chains(label, predicted, enriched, inventory, cfg["duration_sec"])
        write(out / "chain_audits" / f"predicted_chains_{label}.json", {"summary": chain_summary, "chains": rows})

        cost = char_cost_breakdown(planner)
        write(out / f"planner_char_cost_{label}.json", cost)

        saves = save_neighborhood(enriched)
        write(out / "samples" / f"save_neighborhoods_{label}.json", saves)

        summary["matches"][label] = {
            "paths": cfg,
            "provenance_conclusion": prov["conclusion"]["atom_fill_source"],
            "n_raw": len(raw_events),
            "n_enriched": len(enriched.get("events") or []),
            "n_atom_fill": prov["conclusion"]["n_atom_fill_in_enriched"],
            "n_human_causal_chains": prov["conclusion"]["n_human_causal_chains"],
            "n_predicted_chains": len(predicted.get("causal_chains") or []),
            "chain_usability": chain_summary,
            "planner_total_chars": cost["total_chars"],
            "team_attribution_saves": {
                "n_examples": len(saves["examples"]),
                "n_save_center_with_team_fields": sum(
                    1 for x in saves["examples"] if x["team_attribution_from_save_event_fields"]
                ),
                "n_neighborhood_with_team_fields": sum(
                    1 for x in saves["examples"] if x["team_attribution_from_neighborhood_attributes"]
                ),
            },
            "event_field_flags": {
                "has_player_fields_on_events": field_report["has_player_fields_on_events"],
                "has_team_fields_on_events": field_report["has_team_fields_on_events"],
                "has_jersey_or_color_on_events": field_report["has_jersey_or_color_on_events"],
                "example_types_found": {k: len(v) for k, v in samples.items()},
            },
        }

    md = [
        "# SportsCausal Stage 1.1 zero-cost data audit",
        "",
        "- Paid API: **no**",
        "- Algo changes: **no**",
        "- Unit tests re-run: **no**",
        "- Comeback reels regenerated: **no**",
        "",
        "## 1. Provenance of atom_fill",
        "",
        "For both A and B, `enrich_report.source_causal_atoms_only` points at delivery `*_causal.json` files that contain **human `causal_chains[]`** (with `chain_category` / `causal_chain_subtype`).",
        "`atomic_event_enrich.extract_atomic_events` flattens those chain member events by `(type_en, t_ms)` and injects missing ones as `atom_fill_*` with `enrichment.provenance=causal_atom_fill`.",
        "Chain labels are stripped on inject, but the **source of atoms is historical human causal-chain annotations**, not an independent atomic-event annotation file.",
        "A separate API `enrich_with_independent_atoms` exists and forbids `causal_chains`; A/B closed-loop enrich did **not** use it.",
        "",
    ]
    for label, m in summary["matches"].items():
        md += [
            f"### {label}",
            f"- raw events: {m['n_raw']}; enriched: {m['n_enriched']}; atom_fill injected: {m['n_atom_fill']}",
            f"- human causal chains in `*_causal.json`: {m['n_human_causal_chains']}",
            f"- predicted chains: {m['n_predicted_chains']}",
            (
                f"- chain usability: available={m['chain_usability']['fully_available']}, "
                f"partial_unusable={m['chain_usability']['partial_evidence_unusable_as_chain']}, "
                f"fully_unusable={m['chain_usability']['fully_unusable_as_chain']}"
            ),
            f"- planner_request chars: {m['planner_total_chars']}",
            f"- save neighborhood team-field hits: {m['team_attribution_saves']}",
            f"- raw event player/team/jersey flags: {m['event_field_flags']}",
            "",
        ]
    md += [
        "## 2. Event attribute reality check",
        "See `samples/event_fields_*.json` for real Save/Shot/Corner_kick/Goal/Defensive_action objects (not field-name-only).",
        "",
        "## 3. Predicted short-chain audits",
        "Per-chain rows in `chain_audits/predicted_chains_*.json` (category/subtype, span, valid/replay/unbound counts, exclusion reason, partial vs full unusable).",
        "",
        "## 4. Planner request character costs",
        "See `planner_char_cost_*.json` for per-field sums and lossless hoist/omit candidates.",
        "",
        "## 5. Save neighborhoods / team attribution",
        "See `samples/save_neighborhoods_*.json`. If `team_attribution_from_event_fields` is false, belonging cannot be decided from event attributes alone.",
        "",
        "## GitHub",
        "Committed on `research/sportscausal-template-generalization` for external GPT review.",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(md), encoding="utf-8")
    write(out / "SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
