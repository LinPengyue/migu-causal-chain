"""Zero-HTTP narrative-fit regression: time gaps, video triplets, LLM overlay.

All frames are synthetic test bytes. A schema-valid record models a contextual
review, NOT proof that any real football footage improves the story.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from story_video_agent_v3.first_live_window_evidence import (
    SCHEMA as FIRST_LIVE_SCHEMA, TIMELINE_REVIEW_SCHEMA, window_key,
)
from story_video_agent_v3.global_story_critic import structural_diagnosis
from story_video_agent_v3.semantic_story_diagnosis import enrich_issue_semantic_fields
from story_video_agent_v3.story_evidence_search import run_story_evidence_search
from story_video_agent_v3.story_narrative_fit import (
    REJECTED, SCHEMA, SUPPORTED, UNKNOWN, annotate_narrative_fit,
    enforce_narrative_fit_on_plan, validate_narrative_fit_review,
)
from story_video_agent_v3.story_narrative_fit_vlm import (
    run_vlm_narrative_triplet_review,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis

SHA = "d5" * 32
BEFORE = {"segment_id": "before", "role": "deficit_setup",
          "media_in": 10.0, "media_out": 20.0, "include_in_cut": True}
AFTER = {"segment_id": "after", "role": "buildup_action",
         "media_in": 100.0, "media_out": 110.0, "include_in_cut": True}
EDL = [BEFORE, AFTER]
START, END = 30.0, 36.0


def _frame(root: Path, name: str, pts: float, role: str):
    f = root / f"{name}.jpg"
    data = f"synthetic-triplet-{name}".encode("ascii")
    f.write_bytes(data)
    return {"role": role, "path": str(f), "source_pts_sec": pts,
            "sha256": hashlib.sha256(data).hexdigest()}


def _review(root: Path, verdict: str = "SUPPORTS_INSERT"):
    return {
        "schema": SCHEMA,
        "source_sha256": SHA,
        "source_pts_start": START,
        "source_pts_end": END,
        "issue_id": "missing_pressure",
        "before_segment_id": "before",
        "after_segment_id": "after",
        "before_pts_start": 10.0,
        "before_pts_end": 20.0,
        "after_pts_start": 100.0,
        "after_pts_end": 110.0,
        "review_method": "human_video_triplet",
        "verdict": verdict,
        "frame_refs": [
            _frame(root, "before", 15.0, "before"),
            _frame(root, "candidate", 33.0, "candidate"),
            _frame(root, "after", 104.0, "after"),
        ],
        "narrative_review": {
            "story_function": "pressure_escalation",
            "before_to_candidate": "Shows the struggling side beginning to sustain pressure",
            "candidate_to_after": "The attack provides continuity into the subsequent buildup",
            "new_story_information": "Shows a meaningful change in sustained pressure",
            "baseline_comparison": "Without the sequence the pressure change is unexplained",
            "missing_information_addressed": "How the trailing side created attacking momentum",
            "falsifiable_gain": "If the next scene reads as unrelated the insert adds no value",
        },
    }


def _candidate():
    return {
        "candidate_id": "c",
        "issue_id": "missing_pressure",
        "source_pts_start": START, "source_pts_end": END,
        "insert_after_segment_id": "before",
        "before_segment_id": "after",
        "event_id": "e", "event_type": "Shot",
        "executable_safe_revision": True,
    }


def _first_live(root: Path):
    frames = [
        _frame(root, "fl_first", START + 0.5, "candidate"),
        _frame(root, "fl_last", END - 0.5, "candidate"),
    ]
    manifest = {
        "source_sha256": SHA,
        "source_pts_start": START,
        "source_pts_end": END,
        "frame_sha256": [r["sha256"] for r in frames],
    }
    return {
        "schema": FIRST_LIVE_SCHEMA, "source_sha256": SHA,
        "source_pts_start": START, "source_pts_end": END,
        "frames": frames, "manifest": manifest,
        "manifest_digest": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "broadcast_timeline_review": {
            "schema": TIMELINE_REVIEW_SCHEMA,
            "source_sha256": SHA,
            "source_pts_start": START, "source_pts_end": END,
            "outcome": "FIRST_LIVE_VERIFIED",
            "replay_hits": [],
        },
    }


def _search(root: Path, review=None):
    ev = {
        "events": [{
            "event_id": "e", "event_type": "Shot",
            "media_time": {
                "event_time_sec": 33.0,
                "start_time_sec": START, "end_time_sec": END,
            },
            "video_context": {
                "broadcast_phase": "LIVE", "is_replay": False,
                "is_slow_motion": False,
            },
            "scores": {
                "overall_score": 7.0, "emotional_heat_score": 4.0,
                "criticality_score": 2.0,
            },
        }]
    }
    path = root / "events.json"
    path.write_text(json.dumps(ev), encoding="utf-8")
    key = window_key(SHA, START, END)
    diag = {
        "issues": [{
            "issue_id": "missing_pressure", "category": "transition",
            "severity": "major", "evidence_sufficiency": "observed",
            "story_defect_confirmed": True,
            "diagnosis_status": "CONFIRMED_STORY_DEFECT",
            "segment_ids": ["before", "after"],
        }],
        "protected_goal_segment_ids": [],
    }
    report = run_story_evidence_search(
        diagnosis=diag, edl=EDL, events_json=path,
        source_sha256=SHA,
        first_live_evidence_store={"by_key": {key: _first_live(root)}},
        narrative_fit_evidence_store={"by_key": {key: review}} if review else {},
    )
    return diag, report


def _llm_intent():
    return {
        "intent_id": "llm_insert", "issue_id": "missing_pressure",
        "action": "search_add",
        "insert_after_segment_id": "before",
        "before_segment_id": "after",
        "bound_source_window": {"start": START, "end": END},
    }


class TestNarrativeFit(unittest.TestCase):
    def test_label_only_without_triplet_cannot_self_certify(self):
        result = validate_narrative_fit_review(
            {"verdict": "SUPPORTS_INSERT"}, candidate=_candidate(),
            edl=EDL, source_sha=SHA,
        )
        self.assertEqual(result["status"], UNKNOWN)

    def test_triplet_support_can_be_ranked_and_planned(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            diag, report = _search(root, _review(root))
            selected = report["verified_candidates"][0]
            self.assertEqual(selected["narrative_fit_status"], SUPPORTED)
            self.assertTrue(selected["narrative_fit_supports_insert"])
            self.assertTrue(report["executable_search_success"])
            self.assertEqual(len(report["narrative_fit_supported_candidates"]), 1)
            plan = plan_from_diagnosis(
                diag, search_results=report, require_narrative_fit=True,
            )
            self.assertEqual(plan["decision"], "REVISE")
            self.assertEqual(plan["revision_intents"][0]["action"], "search_add")
            self.assertEqual(enforce_narrative_fit_on_plan(
                {"decision": "REVISE", "revision_intents": [_llm_intent()]},
                search_report=report,
            )["narrative_fit_apply_gate"]["n_blocked"], 0)

    def test_first_live_only_does_not_authorize_insert(self):
        with tempfile.TemporaryDirectory() as d:
            diag, report = _search(Path(d))
            self.assertEqual(report["verified_candidates"][0]["narrative_fit_status"], UNKNOWN)
            plan = plan_from_diagnosis(
                diag, search_results=report, require_narrative_fit=True,
            )
            self.assertNotEqual(plan["decision"], "REVISE")
            self.assertFalse(any(i["action"] == "search_add" for i in plan["revision_intents"]))
            gated = enforce_narrative_fit_on_plan(
                {"decision": "REVISE", "revision_intents": [_llm_intent()]},
                search_report=report,
            )
            self.assertEqual(gated["decision"], "UNRESOLVED")
            self.assertEqual(gated["narrative_fit_apply_gate"]["n_blocked"], 1)

    def test_bound_negative_narrative_fit_rejects_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            diag, report = _search(root, _review(root, "REJECT_INSERT"))
            self.assertEqual(report["targets"][0]["n_narrative_fit_rejected"], 1)
            self.assertFalse(report["verified_candidates"])
            self.assertFalse(report["executable_search_success"])

    def test_tampered_context_frame_cannot_approve(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            review = _review(root)
            Path(review["frame_refs"][0]["path"]).write_bytes(b"tampered")
            annotated = annotate_narrative_fit(
                _candidate(), source_sha=SHA, edl=EDL,
                evidence_store={"by_key": {window_key(SHA, START, END): review}},
            )
            self.assertEqual(annotated["narrative_fit_status"], UNKNOWN)
            self.assertEqual(
                annotated["narrative_fit"]["reason"],
                "frame_file_missing_or_digest_mismatch",
            )

    def test_context_anchor_change_invalidates_review(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            review = _review(root)
            c = _candidate()
            c["before_segment_id"] = "different"
            out = validate_narrative_fit_review(
                review, candidate=c, edl=EDL, source_sha=SHA,
            )
            self.assertEqual(out["status"], UNKNOWN)

    def test_llm_wrong_anchor_or_window_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _, report = _search(root, _review(root))
            wrong = _llm_intent()
            wrong["before_segment_id"] = "other"
            out = enforce_narrative_fit_on_plan(
                {"decision": "REVISE", "revision_intents": [wrong]},
                search_report=report,
            )
            self.assertEqual(out["decision"], "UNRESOLVED")
            self.assertEqual(out["revision_intents"][0]["action"], "mark_unresolved")

    def test_source_time_gap_is_not_confirmed_defect(self):
        row = {
            "issue_id": "large_source_jump_first_to_second",
            "category": "transition", "evidence_sufficiency": "needs_video_verify",
            "temporal_discontinuity_only": True,
            "observation": "A large source PTS jump was observed",
            "narrative_problem": "Continuity unknown",
            "segment_ids": ["first", "second"], "severity": "info",
        }
        unbound = enrich_issue_semantic_fields(row, video_semantic_evidence={
            "semantic_evidence": [{
                "issue_id": row["issue_id"],
                "evidence_tier": "DEFECT_CONFIRMED",
                "supports_original_issue": True,
                "observed_fact": "Frames show distant game times",
                "defect_hypothesis": "The cut jumps in time",
                "frame_refs": ["frame1", "frame2"],
            }]
        })
        self.assertFalse(unbound["story_defect_confirmed"])
        self.assertEqual(unbound["diagnosis_status"], "HYPOTHESIS_NEEDS_VIDEO")
        plan = plan_from_diagnosis(
            {"issues": [unbound], "protected_goal_segment_ids": []},
            require_narrative_fit=True,
            keep_unconfirmed_temporal_gap=True,
        )
        self.assertEqual(plan["decision"], "KEEP")
        self.assertEqual(plan["revision_intents"][0]["action"], "keep")

        real_missing = enrich_issue_semantic_fields(row, video_semantic_evidence={
            "semantic_evidence": [{
                "issue_id": row["issue_id"],
                "evidence_tier": "DEFECT_CONFIRMED",
                "supports_original_issue": True,
                "observed_fact": "The previous beat shows the team losing momentum",
                "defect_hypothesis": "The next beat shows unexplained new pressure",
                "missing_story_information": "How the team sustained attacking pressure",
                "why_transition_breaks": "The change in sustained pressure is unmotivated",
                "frame_refs": ["frame1", "frame2"],
            }]
        })
        self.assertTrue(real_missing["story_defect_confirmed"])

    def test_llm_cannot_insert_if_defect_unconfirmed_even_with_review(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _, report = _search(root, _review(root))
            no_defect = {"issues": [{
                "issue_id": "missing_pressure",
                "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
                "story_defect_confirmed": False,
            }]}
            gated = enforce_narrative_fit_on_plan(
                {"decision": "REVISE", "revision_intents": [_llm_intent()]},
                search_report=report, diagnosis=no_defect,
            )
            self.assertEqual(gated["decision"], "UNRESOLVED")
            self.assertEqual(gated["revision_intents"][0]["action"], "mark_unresolved")

    def test_llm_replace_without_source_window_cannot_bypass_fit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            diag, report = _search(root, _review(root))
            attempt = {
                "intent_id": "llm_hidden_replace",
                "action": "replace",
                "issue_id": "missing_pressure",
                "anchor_id": "search:unreviewed_event",
                "target_segment_id": "before",
                "role": "buildup_bridge_action",
            }
            gated = enforce_narrative_fit_on_plan(
                {"decision": "REVISE", "revision_intents": [attempt]},
                search_report=report, diagnosis=diag,
            )
            self.assertEqual(gated["decision"], "UNRESOLVED")
            self.assertEqual(gated["revision_intents"][0]["action"], "mark_unresolved")

    def test_six_frame_vlm_triplet_review_fake_provider_zero_http(self):
        import story_video_agent.frames as frames_module
        import story_video_agent.media as media_module

        class FakeStore:
            def __init__(self, media, *, out_dir, budget):
                self.out_dir = Path(out_dir)
                self.out_dir.mkdir(parents=True, exist_ok=True)
                self.n = 0

            def extract_at(self, t, *, gap_id, tool):
                self.n += 1
                fp = self.out_dir / f"stub_{self.n}.jpg"
                fp.write_bytes(f"frame-{self.n}".encode("ascii"))
                return SimpleNamespace(
                    frame_id=f"fid_{self.n}", path=str(fp),
                    requested_media_sec=t, actual_media_sec=t,
                    pts_status="pts",
                )

            def write_manifest(self, p):
                Path(p).write_text("[]", encoding="utf-8")

        class FakeAPI:
            def __init__(self, incomplete=False):
                self.calls = 0
                self.incomplete = incomplete

            def vision_json(self, *, prompt, frame_paths, frame_ids,
                            mock_obj, frame_bindings):
                self.calls += 1
                assert len(frame_paths) == 6
                cited = (
                    [frame_ids[0]]
                    if self.incomplete else [frame_ids[0], frame_ids[2], frame_ids[4]]
                )
                return {
                    "provider_mode": "real",
                    "content": json.dumps({
                        "verdict": "SUPPORTS_INSERT",
                        "story_function": "pressure_escalation",
                        "before_to_candidate": "The first beat establishes losing momentum",
                        "candidate_to_after": "The candidate prepares the later offensive beat",
                        "new_story_information": "An observable change in the side's possession",
                        "baseline_comparison": "The baseline omits the visible momentum change",
                        "missing_information_addressed": "How the trailing side built attacking momentum",
                        "falsifiable_gain": "If adjacent beats remain unrelated the insert fails",
                        "evidence_frame_ids": cited,
                    }),
                    "usage": {"total_tokens": 100},
                }

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source.mp4"
            source.write_bytes(b"dummy-test-video-not-decoded")
            with mock.patch.object(frames_module, "FrameStore", FakeStore), mock.patch.object(
                media_module, "probe_video", return_value=object(),
            ):
                api = FakeAPI()
                result = run_vlm_narrative_triplet_review(
                    api, source_mp4=source, source_sha=SHA, candidate=_candidate(),
                    edl=EDL, out_dir=root / "good",
                )
                self.assertEqual(api.calls, 1)
                self.assertTrue(result["ok"])
                self.assertEqual(result["validation"]["status"], SUPPORTED)
                bad_api = FakeAPI(incomplete=True)
                bad = run_vlm_narrative_triplet_review(
                    bad_api, source_mp4=source, source_sha=SHA,
                    candidate=_candidate(), edl=EDL, out_dir=root / "bad",
                )
                self.assertEqual(bad_api.calls, 1)
                self.assertFalse(bad["ok"])
                self.assertEqual(bad["validation"]["reason"],
                                 "vlm_triplet_citation_coverage_incomplete")

    def test_structural_gap_critic_marks_observation_not_defect(self):
        source_edl = [
            dict(BEFORE, media_in=0.0, media_out=10.0),
            dict(AFTER, media_in=1500.0, media_out=1510.0),
        ]
        out = structural_diagnosis(edl=source_edl)
        gaps = [i for i in out["issues"] if str(i["issue_id"]).startswith("large_source_jump")]
        self.assertEqual(len(gaps), 1)
        self.assertTrue(gaps[0]["temporal_discontinuity_only"])
        self.assertEqual(gaps[0]["severity"], "info")
        self.assertEqual(gaps[0]["evidence_sufficiency"], "needs_video_verify")


if __name__ == "__main__":
    unittest.main()
