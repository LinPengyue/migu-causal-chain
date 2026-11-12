"""P14 independent event annotations are valid inputs, causal/story gold is not."""
import json
from pathlib import Path
from argparse import Namespace

import pytest

from story_video_agent_v3.atomic_event_enrich import (
    enrich_files, enrich_with_independent_atoms,
)
from story_video_agent_v3.story_full_e2e_cli import build_parser, validate_inputs
from story_video_agent_v3.closed_loop_cli import _audit_goal_segments


def _raw():
    return {"events": [
        {"event_id": "event_1", "event_type": "Pass",
         "media_time": {"event_time_sec": 10.0},
         "video_context": {"broadcast_phase": "LIVE", "is_replay": False}},
    ]}


def test_independent_goal_event_added_without_chain_or_story_labels():
    out = enrich_with_independent_atoms(_raw(), {"atomic_events": [
        {"event_id": "annot_goal", "event_type": "Goal", "t_ms": 12000,
         "broadcast_phase": "UNKNOWN"},
    ]})
    assert len(out["events"]) == 2
    goal = out["events"][1]
    assert goal["event_type"] == "Goal"
    assert goal["media_time"]["event_time_sec"] == 12
    assert goal["video_context"]["broadcast_phase"] == "UNKNOWN"
    assert goal["enrichment"]["provenance"] == "independent_atomic_annotation"
    assert "chain_category" not in goal
    assert out["enrichment_report"]["n_goal_injected"] == 1


def test_duplicate_and_label_leakage_are_rejected():
    raw = _raw()
    atom = {"event_type": "Pass", "t_ms": 10000}
    out = enrich_with_independent_atoms(raw, {"atomic_events": [atom]})
    assert out["enrichment_report"]["n_injected"] == 0
    assert out["enrichment_report"]["n_skipped_duplicate"] == 1
    with pytest.raises(ValueError, match="causal_or_story"):
        enrich_with_independent_atoms(raw, {"atomic_events": [
            {"event_type": "Goal", "t_ms": 12000, "chain_category": "goal"}
        ]})
    with pytest.raises(ValueError, match="causal_or_story"):
        enrich_with_independent_atoms(raw, {"atomic_events": [], "causal_chains": []})


def test_independent_event_enrich_mode_and_no_false_raw_only(tmp_path):
    events = tmp_path / "match.json"
    atoms = tmp_path / "atoms.json"
    events.write_text(json.dumps(_raw()), encoding="utf-8")
    atoms.write_text(json.dumps({"atomic_events": [
        {"event_type": "Goal", "t_ms": 12000, "broadcast_phase": "LIVE"},
    ]}), encoding="utf-8")
    report = enrich_files(
        events_path=events, independent_atoms_path=atoms,
        out_events_path=tmp_path / "enriched.json",
    )
    assert report["input_mode"] == "INDEPENDENT_ATOMIC_ANNOTATED"
    assert report["n_goal_injected"] == 1
    assert not report["eligible_for_raw_only_evaluation"]
    assert report["eligible_for_event_annotated_evaluation"]
    assert report["source_causal_atoms_only"] is None
    with pytest.raises(ValueError, match="mutually_exclusive"):
        enrich_files(
            events_path=events, causal_path=atoms, independent_atoms_path=atoms,
            out_events_path=tmp_path / "other.json",
        )


def test_unknown_goal_is_not_live_candidate(tmp_path):
    ev = enrich_with_independent_atoms(_raw(), {"atomic_events": [
        {"event_type": "Goal", "t_ms": 12000},
    ]})
    p = tmp_path / "enriched.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    predicted = {"causal_chains": [{"events": [
        {"type": "进球", "type_en": "Goal", "t_ms": 12000,
         "event_id": ev["events"][1]["event_id"]},
    ]}]}
    audit = _audit_goal_segments(predicted, p)
    assert audit["n_live_candidate"] == 0
    assert audit["n_unresolved"] == 1


def test_cli_accepts_independent_atoms_but_strict_raw_only_rejects(tmp_path):
    mp4 = tmp_path / "source.mp4"
    mp4.write_bytes(b"video")
    events = tmp_path / "match.json"
    events.write_text(json.dumps(_raw()), encoding="utf-8")
    atoms = tmp_path / "atoms.json"
    atoms.write_text('{"atomic_events":[]}', encoding="utf-8")
    args = build_parser().parse_args([
        "--source-mp4", str(mp4), "--events-json", str(events),
        "--independent-atoms-json", str(atoms), "--out-dir", str(tmp_path / "run"),
    ])
    assert validate_inputs(args) == []
    args.strict_raw_only = True
    assert "strict_raw_only_rejects_external_event_annotations" in validate_inputs(args)
    args.strict_raw_only = False
    args.causal_json = atoms
    assert "independent_atoms_and_causal_gold_mutually_exclusive" in validate_inputs(args)
