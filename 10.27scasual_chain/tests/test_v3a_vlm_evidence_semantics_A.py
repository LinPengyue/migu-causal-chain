"""Zero-cost VLM evidence semantics: OLD/NEW Qwen conflict + Verifier skip.

HTTP=0. Uses saved real-run VLM JSON only; no paid API; no frozen EDL mutation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from story_video_agent_v3.one_round_opening_budget import OPENING_SEGMENT_ID
from story_video_agent_v3.revision_planner import edl_rows_sha256
from story_video_agent_v3.self_revise_agent import (
    authorize_bound_segment,
    build_bound_segment_from_observations,
    evaluate_trim_bounds,
    run_self_revise,
)
from story_video_agent_v3.vlm_evidence_semantics import (
    EVIDENCE_AMBIGUOUS,
    EVIDENCE_SUPPORTS_CANDIDATE_BIND,
    classify_goal_action_evidence,
    persist_visible_model_output,
    redact_audit_value,
    text_mentions_scoreboard_zero_zero,
)

ROOT = Path("/data2/lpy1/_story_va_outputs/v3/plan2")
OLD_RUN = ROOT / "A_one_round_opening_20261106_133900"
NEW_RUN = ROOT / "A_post_vlm_real_20261106_151951"
FRESH_BASELINE = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136/05_v3a/_baseline_phase5"
)
FIX = Path(__file__).resolve().parent / "fixtures" / "v3a_post_vlm_revision_A"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _edl_rows(obj):
    if isinstance(obj, list):
        return obj
    return obj.get("segments") or obj.get("edl") or obj.get("rows") or []


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _real_vlm(run: Path) -> Dict[str, Any]:
    return _load(run / "round_01/vlm_observations.json")["observations"][0]["vlm"]


def _frames_from_run(run: Path) -> List[Dict[str, Any]]:
    obs = _load(run / "round_01/vlm_observations.json")["observations"][0]
    frames = list(obs.get("frames") or [])
    if frames:
        return frames
    # Reconstruct minimal PTS bindings from sample_times / manifest
    times = obs.get("sample_times") or [1334.64, 1336.36, 1337.76, 1339.16]
    out = []
    for i, t in enumerate(times):
        out.append({
            "frame_id": f"f_{i:04d}",
            "actual_media_sec": float(t),
            "requested_media_sec": float(t),
            "pts_status": "pts",
        })
    return out


class RealQwenConflictSemanticsTests(unittest.TestCase):
    @unittest.skipUnless(
        (OLD_RUN / "round_01/vlm_observations.json").is_file()
        and (NEW_RUN / "round_01/vlm_observations.json").is_file(),
        "OLD/NEW VLM artifacts missing",
    )
    def test_new_conflict_is_ambiguous_old_supports_bindable(self) -> None:
        old = _real_vlm(OLD_RUN)
        new = _real_vlm(NEW_RUN)
        old_c = classify_goal_action_evidence(old)
        new_c = classify_goal_action_evidence(new)
        self.assertEqual(old_c["status"], EVIDENCE_SUPPORTS_CANDIDATE_BIND)
        self.assertTrue(old_c["bindable"])
        self.assertEqual(new_c["status"], EVIDENCE_AMBIGUOUS)
        self.assertFalse(new_c["bindable"])
        self.assertIn("explicit_supports_bound_segment_false", new_c["reasons"])
        self.assertIn("shot_and_net_conflict_with_supports_false", new_c["reasons"])
        # Legacy observed_net must not be treated as goal confirmation.
        self.assertIs(new.get("observed_net"), True)
        self.assertIs(new.get("supports_bound_segment"), False)
        self.assertTrue(text_mentions_scoreboard_zero_zero(new.get("visible_content")))
        self.assertTrue(text_mentions_scoreboard_zero_zero(old.get("visible_content")))

    @unittest.skipUnless(
        (NEW_RUN / "round_01/vlm_observations.json").is_file(),
        "NEW VLM artifact missing",
    )
    def test_authorize_rejects_new_conflict_despite_shot_net(self) -> None:
        new = _real_vlm(NEW_RUN)
        frames = _frames_from_run(NEW_RUN)
        auth = authorize_bound_segment(
            media_in=1325.123,
            media_out=1347.123,
            role="opponent_opening_goal_action",
            frames=frames,
            vlm=new,
            trusted_windows=[{"start": 1321.123, "end": 1351.123}],
            score_anchor_sec=None,
        )
        self.assertFalse(auth["allow"])
        self.assertEqual(auth.get("evidence_status"), EVIDENCE_AMBIGUOUS)
        self.assertIn(EVIDENCE_AMBIGUOUS, auth.get("denies") or [])
        self.assertTrue(auth.get("observed_net_is_not_goal_confirmation"))

    @unittest.skipUnless(
        (OLD_RUN / "round_01/vlm_observations.json").is_file(),
        "OLD VLM artifact missing",
    )
    def test_authorize_allows_old_explicit_supports_with_shot(self) -> None:
        old = _real_vlm(OLD_RUN)
        frames = _frames_from_run(OLD_RUN)
        auth = authorize_bound_segment(
            media_in=1325.123,
            media_out=1347.123,
            role="opponent_opening_goal_action",
            frames=frames,
            vlm=old,
            trusted_windows=[{"start": 1321.123, "end": 1351.123}],
            score_anchor_sec=None,
        )
        self.assertTrue(auth["allow"])
        self.assertEqual(auth.get("evidence_status"), "CANDIDATE_BOUND_UNVERIFIED_FIRST_LIVE")
        self.assertEqual(auth.get("first_live_status"), "NOT_VERIFIED")

    def test_shot_net_without_supports_is_ambiguous_not_bindable(self) -> None:
        vlm = {
            "observed_shot": True,
            "observed_net": True,
            "supports_bound_segment": None,
            "visible_content": "ball near net",
        }
        c = classify_goal_action_evidence(vlm)
        self.assertEqual(c["status"], EVIDENCE_AMBIGUOUS)
        self.assertFalse(c["bindable"])
        auth = authorize_bound_segment(
            media_in=100.0,
            media_out=120.0,
            role="opponent_opening_goal_action",
            frames=[{"frame_id": "f", "actual_media_sec": 110.0, "pts_status": "pts"}],
            vlm=vlm,
            trusted_windows=[{"start": 90.0, "end": 130.0}],
        )
        self.assertFalse(auth["allow"])
        self.assertIn(EVIDENCE_AMBIGUOUS, auth.get("denies") or [])

    def test_candidate_span_cannot_override_supports_false(self) -> None:
        vlm = {
            "observed_shot": True,
            "observed_net": True,
            "supports_bound_segment": False,
            "candidate_goal_action_span": {"start": 110.0, "end": 115.0},
            "visible_content": "UAE 0-0 OMA; no goal",
        }
        auth = authorize_bound_segment(
            media_in=110.0,
            media_out=115.0,
            role="opponent_opening_goal_action",
            frames=[
                {"frame_id": "a", "actual_media_sec": 111.0, "pts_status": "pts"},
                {"frame_id": "b", "actual_media_sec": 114.0, "pts_status": "pts"},
            ],
            vlm=vlm,
            trusted_windows=[{"start": 100.0, "end": 130.0}],
        )
        self.assertFalse(auth["allow"])
        self.assertEqual(auth.get("evidence_status"), EVIDENCE_AMBIGUOUS)


class TrimAndBindWeakEvidenceTests(unittest.TestCase):
    def _row(self) -> Dict[str, Any]:
        return {
            "segment_id": OPENING_SEGMENT_ID,
            "role": "opponent_opening_goal_action",
            "media_in": 1325.123,
            "media_out": 1347.123,
            "include_in_cut": True,
        }

    def test_trim_rejects_supports_false_even_with_shot_net_span(self) -> None:
        obs = {
            "request_id": "conflict_obs",
            "issue_id": "SYN_OFFSET",
            "ok": True,
            "window": {"start": 1325.123, "end": 1347.123},
            "frames": [
                {"frame_id": f"f{i}", "actual_media_sec": t, "pts_status": "pts"}
                for i, t in enumerate([1326.0, 1327.5, 1329.0, 1330.5])
            ],
            "vlm": {
                "observed_shot": True,
                "observed_net": True,
                "supports_bound_segment": False,
                "live_or_replay": "live",
                "candidate_goal_action_span": {"start": 1326.0, "end": 1331.0},
                "visible_content": "scoreboard 0-0; no goal scored",
            },
        }
        te = evaluate_trim_bounds(
            intent={
                "intent_id": "t",
                "action": "trim",
                "issue_id": "SYN_OFFSET",
                "target_segment_id": OPENING_SEGMENT_ID,
            },
            row=self._row(),
            observations=[obs],
        )
        self.assertFalse(te.get("ok"))
        self.assertEqual(te.get("reason"), EVIDENCE_AMBIGUOUS)

    def test_trim_still_allows_explicit_supports_with_shot_and_span(self) -> None:
        obs = {
            "request_id": "good_obs",
            "issue_id": "SYN_OFFSET",
            "ok": True,
            "window": {"start": 1325.123, "end": 1347.123},
            "frames": [
                {"frame_id": f"f{i}", "actual_media_sec": t, "pts_status": "pts"}
                for i, t in enumerate([1326.0, 1327.5, 1329.0, 1330.5])
            ],
            "vlm": {
                "observed_shot": True,
                "observed_net": True,
                "supports_bound_segment": True,
                "live_or_replay": "live",
                "candidate_goal_action_span": {"start": 1326.0, "end": 1331.0},
            },
        }
        te = evaluate_trim_bounds(
            intent={
                "intent_id": "t",
                "action": "trim",
                "issue_id": "SYN_OFFSET",
                "target_segment_id": OPENING_SEGMENT_ID,
            },
            row=self._row(),
            observations=[obs],
        )
        self.assertTrue(te.get("ok"))
        self.assertEqual(te.get("evidence_classification"), EVIDENCE_SUPPORTS_CANDIDATE_BIND)

    def test_build_bound_refuses_ambiguous_new_style(self) -> None:
        vlm = {
            "observed_shot": True,
            "observed_net": True,
            "supports_bound_segment": False,
            "candidate_goal_action_span": {"start": 1326.0, "end": 1331.0},
            "live_or_replay": "live",
            "visible_content": "0-0 no goal",
        }
        obs = {
            "request_id": "amb",
            "ok": True,
            "window": {"start": 1325.123, "end": 1347.123},
            "frames": [
                {"frame_id": f"f{i}", "actual_media_sec": t, "pts_status": "pts"}
                for i, t in enumerate([1326.0, 1327.5, 1329.0, 1330.5])
            ],
            "vlm": vlm,
            "allowed_windows": [{"start": 1321.123, "end": 1351.123}],
        }
        bound = build_bound_segment_from_observations(
            intent={
                "intent_id": "b",
                "role": "opponent_opening_goal_action",
                "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
            },
            observations=[obs],
            trusted_windows=[{"start": 1321.123, "end": 1351.123}],
            score_anchor_sec=None,
        )
        self.assertFalse(bound.get("ok"))
        self.assertEqual(bound.get("reason"), EVIDENCE_AMBIGUOUS)

    def test_zero_zero_alone_neither_supports_nor_disproves(self) -> None:
        only_score = {
            "visible_content": "Scoreboard shows UAE 0-0 OMA",
            "observed_shot": None,
            "observed_net": None,
            "supports_bound_segment": None,
        }
        c = classify_goal_action_evidence(only_score)
        self.assertFalse(c["bindable"])
        self.assertIn("scoreboard_zero_zero_alone_not_proof", " ".join(c["reasons"]))


class PersistVisibleOutputTests(unittest.TestCase):
    def test_persist_full_content_redacts_secrets_and_base64(self) -> None:
        long_b64 = "A" * 400
        with tempfile.TemporaryDirectory() as td:
            info = persist_visible_model_output(
                Path(td),
                role="verifier",
                request_id="attempt_0",
                content='{"issues":[' + ("x" * 5000) + "]}",
                meta={
                    "api_key": "sk-secret",
                    "Authorization": "Bearer tok",
                    "usage": {"completion_tokens": 2048},
                    "image": f"data:image/jpeg;base64,{long_b64}",
                },
            )
            self.assertTrue(info["persisted"])
            path = Path(info["visible_output_path"])
            blob = _load(path)
            self.assertGreater(blob["visible_output_chars"], 2000)
            self.assertEqual(blob["content"], '{"issues":[' + ("x" * 5000) + "]}")
            self.assertEqual(blob["meta"]["api_key"], "[REDACTED]")
            self.assertEqual(blob["meta"]["Authorization"], "[REDACTED]")
            self.assertIn("REDACTED_DATA_URI_IMAGE", blob["meta"]["image"])
            self.assertNotIn("sk-secret", path.read_text(encoding="utf-8"))

    def test_redact_helper_on_nested(self) -> None:
        out = redact_audit_value({"headers": {"authorization": "Bearer x"}, "ok": True})
        self.assertEqual(out["headers"]["authorization"], "[REDACTED]")
        self.assertTrue(out["ok"])


@unittest.skipUnless(
    (FRESH_BASELINE / "candidate_edl.json").is_file()
    and (FIX / "rp_unresolved.json").is_file(),
    "baseline or UNRESOLVED fixture missing",
)
class SkipVerifierMainLoopTests(unittest.TestCase):
    def test_unresolved_no_edl_change_skips_http_verifier(self) -> None:
        """RP UNRESOLVED + identical EDL → NO_CANDIDATE_CHANGE; inject never runs."""
        baseline_edl = _edl_rows(_load(FRESH_BASELINE / "candidate_edl.json"))
        pre_sha = edl_rows_sha256(baseline_edl)
        frozen = _file_sha(FRESH_BASELINE / "candidate_edl.json")
        obs = {
            "request_id": "new_vlm_observation",
            "issue_id": "U01",
            "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
            "ok": True,
            "provider_mode": "offline_fixture",
            "window": {"start": 1325.123, "end": 1347.123},
            "frames": [
                {"frame_id": f"f{i}", "actual_media_sec": t, "pts_status": "pts"}
                for i, t in enumerate([1334.64, 1336.36, 1337.76, 1339.16])
            ],
            "fact_verified": False,
            "observation_only": True,
            "counts_as_new_http": False,
            "vlm": {
                "visible_content": "NEW-style conflict: 0-0 and no goal; shot/net true",
                "story_relation": "scoreboard remains 0-0",
                "observed_shot": True,
                "observed_net": True,
                "supports_bound_segment": False,
                "live_or_replay": "live",
                "candidate_goal_action_span": None,
                "scoreboard_only": False,
                "fact_verified": False,
                "observation_only": True,
            },
        }
        planner = {
            "diagnoses": [{
                "issue_id": "U01",
                "problem": "opening inspect",
                "severity": "P2",
                "target_segment_id": OPENING_SEGMENT_ID,
            }],
            "revision_intents": [{
                "intent_id": "pre",
                "action": "keep",
                "disposition": "INSPECT",
                "target_segment_id": OPENING_SEGMENT_ID,
                "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
                "rationale": "pre-vlm",
            }],
            "video_tool_requests": [],
            "notes": "skip_verifier_offline",
        }
        rp = _load(FIX / "rp_unresolved.json")
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            pf = td_path / "planner.json"
            rpf = td_path / "rp.json"
            vf = td_path / "ver.json"
            pf.write_text(json.dumps(planner), encoding="utf-8")
            rpf.write_text(json.dumps(rp), encoding="utf-8")
            # Verifier fixture would succeed if called — inject forces failure if called.
            vf.write_text(json.dumps({
                "issues": [],
                "dimensions": {
                    "story_element_coverage": {"status": "unchanged", "score": 80},
                    "narrative_coherence": {"status": "unchanged", "score": 80},
                    "image_content_quality": {"status": "unchanged", "score": 80},
                    "live_authenticity": {"status": "unchanged", "score": 80},
                },
                "quality_delta_vs_baseline": "unchanged",
                "hard_vetoes": [],
                "evidence_of_improvement": [],
            }), encoding="utf-8")
            out = td_path / "out"
            summary = run_self_revise(
                phase5_dir=FRESH_BASELINE,
                out_dir=out,
                prefer_p1_polish=False,
                planner_fixture=pf,
                revision_planner_fixture=rpf,
                verifier_fixture=vf,
                enable_post_vlm_revision=True,
                inject_verifier_failure=True,
                skip_vlm=True,
                max_rounds=1,
                allow_degraded_offline=True,
                seed_observations=[obs],
            )
            dual = _load(out / "round_01/dual_verifier.json")
            self.assertTrue(dual.get("skipped_api_verifier"))
            self.assertEqual(dual.get("skip_reason"), "NO_CANDIDATE_CHANGE")
            self.assertEqual(
                dual.get("semantic_verification_status"),
                "SKIPPED_NO_CANDIDATE_CHANGE",
            )
            r0 = (summary.get("rounds") or [{}])[0]
            self.assertTrue(r0.get("skipped_api_verifier"))
            self.assertEqual(r0.get("verifier_skip_reason"), "NO_CANDIDATE_CHANGE")
            self.assertEqual(r0.get("pre_revision_edl_sha256"), r0.get("post_candidate_edl_sha256"))
            best_sha = edl_rows_sha256(_load(out / "best_candidate_edl.json"))
            self.assertEqual(best_sha, pre_sha)
            self.assertEqual(
                (summary.get("api_usage") or {}).get("http_attempts", 0) or 0, 0,
            )
            self.assertEqual(_file_sha(FRESH_BASELINE / "candidate_edl.json"), frozen)
            # Injected failure must not appear — API Verifier path was skipped.
            self.assertNotIn("injected", str(dual.get("error") or "").lower())
            self.assertNotIn("injected", str((dual.get("api") or {}).get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
