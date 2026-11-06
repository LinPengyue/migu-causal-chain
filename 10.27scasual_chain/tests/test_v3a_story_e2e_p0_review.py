"""P0 review regressions for story-level E2E (match-agnostic, HTTP=0)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.frames import FrameBudget, FrameBudgetExhausted, FrameStore
from story_video_agent_v3.global_story_critic import structural_diagnosis
from story_video_agent_v3.one_round_opening_budget import filter_tools_to_focus
from story_video_agent_v3.self_revise_agent import decide_accept
from story_video_agent_v3.story_e2e_agent import StoryE2EInputs, resolve_baseline
from story_video_agent_v3.story_observe import _extract_ordered


class FrameBudgetSoftFailTests(unittest.TestCase):
    def test_extract_ordered_soft_fails(self):
        class _FakeStore:
            def extract_at(self, *a, **k):
                raise FrameBudgetExhausted("budget gone")

        pack = _extract_ordered(_FakeStore(), [1.0, 2.0], gap_id="g")
        self.assertTrue(pack["frame_budget_exhausted"])
        self.assertEqual(pack["frames"], [])
        self.assertIn("FrameBudgetExhausted", pack["error"] or "")


class DecideAcceptVideoEvidenceTests(unittest.TestCase):
    def _audits(self):
        base = {
            "hard_gate_findings": [],
            "dimensions": {
                "story_element_coverage": {"score": 80.0},
                "story_coherence": {"score": 70.0},
            },
        }
        cand = {
            "hard_gate_findings": [],
            "dimensions": {
                "story_element_coverage": {"score": 80.0},
                "story_coherence": {"score": 95.0},  # structural proxy up
            },
        }
        return base, cand

    def test_claim_only_eoi_does_not_accept(self):
        base, cand = self._audits()
        edl = [
            {"segment_id": "a", "role": "buildup_action", "media_in": 1, "media_out": 5,
             "include_in_cut": True},
            {"segment_id": "g", "role": "equalizer_goal_action", "media_in": 10, "media_out": 20,
             "include_in_cut": True, "is_replay": False},
        ]
        cand_edl = [dict(edl[1])]  # soft drop via meta
        meta = {
            "applied": [{
                "intent": "i", "action": "drop", "status": "applied",
                "segment_id": "a",
            }],
            "rejected": [],
        }
        d = decide_accept(
            baseline_audit=base,
            candidate_audit=cand,
            verifier={
                "ok": True,
                "ok_for_semantic_accept": True,
                "validated": {
                    "hard_vetoes": [],
                    "dimensions": {
                        "narrative_coherence": {
                            "status": "improved",
                            "summary": "better",
                            "evidence_refs": [],  # no video refs
                        }
                    },
                    "evidence_of_improvement": [
                        {"claim": "story feels better", "evidence_refs": []}
                    ],
                    "quality_delta_vs_baseline": "improved",
                },
            },
            revision_meta=meta,
            baseline_edl=edl,
            candidate_edl=cand_edl,
            semantic_verification_status="PASSED",
        )
        self.assertFalse(d["accept"], d["reasons"])
        self.assertTrue(
            any(
                "without_video" in r or "claim_only" in r or "structural_proxy" in r
                for r in d["reasons"]
            ),
            d["reasons"],
        )

    def test_video_backed_eoi_can_accept_soft_edit(self):
        base, cand = self._audits()
        edl = [
            {"segment_id": "a", "role": "buildup_action", "media_in": 1, "media_out": 5,
             "include_in_cut": True},
            {"segment_id": "g", "role": "equalizer_goal_action", "media_in": 10, "media_out": 20,
             "include_in_cut": True, "is_replay": False},
        ]
        cand_edl = [dict(edl[1])]
        meta = {
            "applied": [{
                "intent": "i", "action": "drop", "status": "applied",
                "segment_id": "a",
            }],
        }
        d = decide_accept(
            baseline_audit=base,
            candidate_audit=cand,
            verifier={
                "ok": True,
                "ok_for_semantic_accept": True,
                "validated": {
                    "hard_vetoes": [],
                    "dimensions": {
                        "narrative_coherence": {
                            "status": "improved",
                            "summary": "dropped empty broll",
                            "evidence_refs": [{"kind": "observation", "ref": "obs_mid_01"}],
                        }
                    },
                    "evidence_of_improvement": [{
                        "claim": "removed empty buildup",
                        "evidence_refs": [{"kind": "frame", "frame_id": "f1"}],
                    }],
                    "quality_delta_vs_baseline": "improved",
                },
            },
            revision_meta=meta,
            baseline_edl=edl,
            candidate_edl=cand_edl,
            semantic_verification_status="PASSED",
        )
        self.assertTrue(d["accept"], d["reasons"])
        self.assertEqual(d["path"], "quality_improvement")


class MultiFocusSegmentTests(unittest.TestCase):
    def test_filter_keeps_all_focus_ids(self):
        tools = [
            {"request_id": "t1", "anchor_id": "edl:seg_a", "tool": "extract_frames"},
            {"request_id": "t2", "anchor_id": "edl:seg_b", "tool": "extract_frames"},
            {"request_id": "t3", "anchor_id": "edl:seg_c", "tool": "extract_frames"},
        ]
        out = filter_tools_to_focus(
            tools, focus_segment_ids=["seg_a", "seg_b"], max_tools=5,
        )
        kept_aids = {t["anchor_id"] for t in out["tools"]}
        self.assertEqual(kept_aids, {"edl:seg_a", "edl:seg_b"})
        self.assertEqual(set(out["matched_focus_ids"]), {"seg_a", "seg_b"})
        # Must not silently keep only the first focus id's tools when both match.
        self.assertEqual(len(out["tools"]), 2)


class NarrativeCriticOrderTests(unittest.TestCase):
    def test_development_after_climax_flagged(self):
        edl = [
            {"segment_id": "g1", "role": "go_ahead_goal_action", "include_in_cut": True,
             "media_in": 100, "media_out": 120, "is_replay": False},
            {"segment_id": "b1", "role": "buildup_action", "include_in_cut": True,
             "media_in": 200, "media_out": 220, "is_replay": False},
        ]
        diag = structural_diagnosis(edl=edl)
        ids = [i["issue_id"] for i in diag["issues"]]
        self.assertIn("development_after_climax", ids)
        blob = str(diag)
        for banned in ("阿联酋", "阿曼", "奥萨苏纳", "克罗地亚"):
            self.assertNotIn(banned, blob)


class RawInputHonestyTests(unittest.TestCase):
    def test_json_mp4_alone_not_sufficient(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mj = root / "match.json"
            mj.write_text("{}", encoding="utf-8")
            # tiny fake mp4 path — need is_file; create empty
            mp4 = root / "match.mp4"
            mp4.write_bytes(b"\x00")
            out = root / "out"
            out.mkdir()
            staged = resolve_baseline(
                StoryE2EInputs(match_json=mj, source_mp4=mp4, out_dir=out)
            )
            self.assertFalse(staged.get("ok"))
            self.assertFalse(staged.get("raw_json_mp4_sufficient"))
            self.assertTrue(staged.get("raw_only_attempt_detected"))


if __name__ == "__main__":
    unittest.main()
