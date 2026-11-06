"""Zero-cost audit regressions: Qwen divergence evidence + Verifier truncation/skip.

HTTP=0. Uses saved real-run artifacts and offline mocks only.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

from story_video_agent.vision_provider import EvidenceNormalizationError, _extract_json_obj
from story_video_agent_v3.hybrid_fallback import (
    SKIP_REASON_NO_CANDIDATE_CHANGE,
    build_no_candidate_change_dual,
    should_skip_api_verifier_no_candidate_change,
)
from story_video_agent_v3.self_revise_agent import (
    _parse_model_json,
    _verifier_output_budget_truncated,
    call_llm_verifier,
    validate_verifier_output,
)

ROOT = Path("/data2/lpy1/_story_va_outputs/v3/plan2")
OLD_RUN = ROOT / "A_one_round_opening_20261106_133900"
NEW_RUN = ROOT / "A_post_vlm_real_20261106_151951"
FRAMES = (
    "f_0000_1334623.jpg",
    "f_0001_1336323.jpg",
    "f_0002_1337723.jpg",
    "f_0003_1339123.jpg",
)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class FrameIdentityAuditTests(unittest.TestCase):
    def test_four_frames_byte_identical_across_runs(self) -> None:
        if not (OLD_RUN / "round_01/vlm/frames").is_dir():
            self.skipTest("old run artifacts missing")
        if not (NEW_RUN / "round_01/vlm/frames").is_dir():
            self.skipTest("new run artifacts missing")
        for name in FRAMES:
            old_p = OLD_RUN / "round_01/vlm/frames" / name
            new_p = NEW_RUN / "round_01/vlm/frames" / name
            self.assertEqual(_sha256(old_p), _sha256(new_p), name)

    def test_qwen_structured_fields_diverge_with_prose_conflict_on_new(self) -> None:
        if not (NEW_RUN / "round_01/vlm_observations.json").is_file():
            self.skipTest("new VLM obs missing")
        old = _load(OLD_RUN / "round_01/vlm_observations.json")["observations"][0]["vlm"]
        new = _load(NEW_RUN / "round_01/vlm_observations.json")["observations"][0]["vlm"]
        self.assertTrue(old.get("supports_bound_segment"))
        self.assertFalse(new.get("supports_bound_segment"))
        # NEW: boolean shot/net true while prose denies a goal — field/prose conflict,
        # not a local parse-mapping rewrite.
        self.assertIs(new.get("observed_shot"), True)
        self.assertIs(new.get("observed_net"), True)
        prose = f"{new.get('visible_content')} {new.get('story_relation')}".lower()
        self.assertTrue("0-0" in prose or "no goal" in prose)


class VerifierTruncationOfflineReproduceTests(unittest.TestCase):
    def test_saved_excerpt_fails_at_parse_not_validate(self) -> None:
        path = NEW_RUN / "round_01/dual_verifier.json"
        if not path.is_file():
            self.skipTest("new dual_verifier missing")
        dual = _load(path)
        excerpt = str((dual.get("api") or {}).get("raw_excerpt") or "")
        self.assertGreater(len(excerpt), 100)
        with self.assertRaises(EvidenceNormalizationError) as ctx:
            _extract_json_obj(excerpt)
        self.assertIn("invalid JSON object", str(ctx.exception))
        with self.assertRaises(EvidenceNormalizationError):
            _parse_model_json(excerpt)
        # Production error string shape
        try:
            _parse_model_json(excerpt)
        except Exception as exc:
            shaped = f"STRUCTURED_PARSE_FAIL:{type(exc).__name__}:{exc}"
            self.assertEqual(
                shaped,
                "STRUCTURED_PARSE_FAIL:EvidenceNormalizationError:invalid JSON object",
            )

    def test_real_run_usage_shows_length_at_2048_ceiling(self) -> None:
        path = NEW_RUN / "self_revise_summary.json"
        if not path.is_file():
            self.skipTest("new summary missing")
        records = (_load(path).get("api_usage") or {}).get("records") or []
        ver = [r for r in records if r.get("role") == "verifier"]
        self.assertEqual(len(ver), 1)
        self.assertEqual(ver[0].get("completion_tokens"), 2048)
        self.assertEqual(ver[0].get("finish_reason"), "length")
        self.assertEqual(ver[0].get("request_token_limit"), 2048)
        # Pre-fix audit: equality was not flagged (ct > limit). Post-fix uses >=.
        self.assertFalse(ver[0].get("output_budget_exceeded"))

    def test_call_llm_verifier_classifies_output_budget_truncation(self) -> None:
        truncated = (
            '{\n  "issues": [\n    {\n      "issue_id": "I01",\n'
            '      "problem": "unterminated'
        )
        api = mock.Mock()
        api.verify_decision.return_value = {
            "provider_mode": "real",
            "content": truncated,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 2048,
                "total_tokens": 2148,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
            "est_cost_usd": 0.001,
            "finish_reason": "length",
            "response_audit": {
                "output_token_limit": 2048,
                "output_budget_exceeded": True,
                "finish_reason": "length",
            },
            "model": "DeepSeek-V4-Pro-0813",
        }
        out = call_llm_verifier(api, {"baseline_hard_gates": []}, max_retries=0)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("failure_code"), "OUTPUT_BUDGET_TRUNCATION")
        self.assertEqual(out.get("finish_reason"), "length")
        self.assertEqual(out.get("parse_stage"), "_parse_model_json")
        self.assertIn("OUTPUT_BUDGET_TRUNCATION", str(out.get("error")))
        # Must not pretend validate succeeded
        self.assertNotIn("validated", out)

    def test_truncation_helper_equality_and_finish_reason(self) -> None:
        self.assertTrue(
            _verifier_output_budget_truncated(
                {
                    "finish_reason": "length",
                    "usage": {"completion_tokens": 100},
                    "response_audit": {"output_token_limit": 2048},
                }
            )
        )
        self.assertTrue(
            _verifier_output_budget_truncated(
                {
                    "finish_reason": "stop",
                    "usage": {"completion_tokens": 2048},
                    "response_audit": {"output_token_limit": 2048},
                }
            )
        )
        self.assertFalse(
            _verifier_output_budget_truncated(
                {
                    "finish_reason": "stop",
                    "usage": {"completion_tokens": 412},
                    "response_audit": {"output_token_limit": 2048},
                }
            )
        )


class NoCandidateChangeSkipTests(unittest.TestCase):
    def test_should_skip_when_unresolved_and_sha_identical(self) -> None:
        reason = should_skip_api_verifier_no_candidate_change(
            revision_planner_decision="UNRESOLVED",
            pre_revision_edl_sha256="abc",
            post_revision_edl_sha256="abc",
            evidence_bound_count=0,
        )
        self.assertEqual(reason, SKIP_REASON_NO_CANDIDATE_CHANGE)

    def test_should_skip_keep_with_new_evidence(self) -> None:
        reason = should_skip_api_verifier_no_candidate_change(
            revision_planner_decision="KEEP_WITH_NEW_EVIDENCE",
            pre_revision_edl_sha256="abc",
            post_revision_edl_sha256="abc",
            evidence_bound_count=0,
        )
        self.assertEqual(reason, SKIP_REASON_NO_CANDIDATE_CHANGE)

    def test_no_skip_when_sha_differs_or_bound(self) -> None:
        self.assertIsNone(
            should_skip_api_verifier_no_candidate_change(
                revision_planner_decision="UNRESOLVED",
                pre_revision_edl_sha256="abc",
                post_revision_edl_sha256="def",
                evidence_bound_count=0,
            )
        )
        self.assertIsNone(
            should_skip_api_verifier_no_candidate_change(
                revision_planner_decision="UNRESOLVED",
                pre_revision_edl_sha256="abc",
                post_revision_edl_sha256="abc",
                evidence_bound_count=1,
            )
        )
        self.assertIsNone(
            should_skip_api_verifier_no_candidate_change(
                revision_planner_decision="PROPOSE_REPAIR",
                pre_revision_edl_sha256="abc",
                post_revision_edl_sha256="abc",
                evidence_bound_count=0,
            )
        )

    def test_build_no_candidate_change_dual_skips_api_fn(self) -> None:
        called = {"n": 0}

        def boom(*_a, **_k):
            called["n"] += 1
            raise AssertionError("API verifier must not be called")

        # build_no_candidate_change_dual does not take api_fn; ensure shape only.
        story = {"match_id": "t"}
        plan = {"beats": []}
        edl = [{"segment_id": "s1", "include_in_cut": True, "media_in": 1.0, "media_out": 2.0}]
        with mock.patch(
            "story_video_agent_v3.hybrid_fallback.run_rule_verifier",
            return_value={
                "track": "rule",
                "ok": True,
                "rule_verification_status": "PASSED",
                "audit": {},
                "p0_count": 0,
            },
        ):
            dual = build_no_candidate_change_dual(
                story=story, plan=plan, baseline_edl=edl, candidate_edl=edl
            )
        self.assertTrue(dual.get("skipped_api_verifier"))
        self.assertEqual(dual.get("skip_reason"), SKIP_REASON_NO_CANDIDATE_CHANGE)
        self.assertEqual(dual.get("semantic_verification_status"), "SKIPPED_NO_CANDIDATE_CHANGE")
        self.assertFalse(dual.get("ok_for_semantic_accept"))
        self.assertEqual((dual.get("api") or {}).get("est_cost_usd"), 0.0)
        self.assertEqual(called["n"], 0)
        # Ensure a successful fixture still validates (control: validate path works)
        ok_raw = {
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
        }
        validated = validate_verifier_output(ok_raw)
        self.assertTrue(validated.get("validated"))


class ApiCeilingEqualityTests(unittest.TestCase):
    def test_completion_tokens_equal_limit_marks_exceeded(self) -> None:
        from story_video_agent.api_provider import ApiProvider, EndpointConfig

        cfg = EndpointConfig(
            role="verifier",
            base_url="https://example.test/v1",
            api_key="sk-x",
            model="m",
            token_param="max_tokens",
            max_completion_tokens=2048,
        )
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs={"verifier": cfg},
            max_calls=2,
            max_completion_tokens=2048,
            required_roles=["verifier"],
        )

        def fake_post(_cfg, *, body):
            self.assertEqual(body.get("max_tokens"), 2048)
            return {
                "choices": [
                    {"message": {"content": "{" + ("x" * 20)}, "finish_reason": "length"}
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2048,
                    "total_tokens": 2058,
                },
            }

        with mock.patch.object(api, "_post_chat", side_effect=fake_post):
            r = api.chat(
                role="verifier",
                messages=[{"role": "user", "content": "a"}],
                cache_key="ceil",
                allow_degraded_fallback=False,
            )
        self.assertTrue(r["response_audit"]["output_budget_exceeded"])
        self.assertEqual(r["usage"]["completion_tokens"], 2048)
        self.assertEqual(api.stats.calls[-1].finish_reason, "length")
        self.assertTrue(api.stats.calls[-1].output_budget_exceeded)


if __name__ == "__main__":
    unittest.main()
