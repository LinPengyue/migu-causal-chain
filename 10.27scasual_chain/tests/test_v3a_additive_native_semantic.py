"""Mock-only tests: no paid provider calls or real MP4s required."""
import json
from pathlib import Path

from story_video_agent_v3 import story_additive_native_semantic as m


def _pack(tmp_path):
    baseline = tmp_path / "finished_seam.mp4"
    candidate = tmp_path / "source_candidate.mp4"
    baseline.write_bytes(b"finished story video")
    candidate.write_bytes(b"original source video")
    return {
        "source_sha256": "a" * 64,
        "review_items": [{
            "opportunity_id": "bridge-1",
            "finished_story_context": {"ok": True, "path": str(baseline)},
            "source_context_clips": [{
                "media_in": 900.0, "media_out": 912.0,
                "export": {"ok": True, "path": str(candidate)},
            }],
        }],
    }


def test_native_review_is_skipped_without_explicit_approval(tmp_path):
    class DoNotCall:
        def chat(self, **kwargs):
            raise AssertionError("must not call provider")
    report = m.review_additive_native_video(
        api=DoNotCall(), pack=_pack(tmp_path),
        out_dir=tmp_path/"skip", approved=False,
        max_calls=2, max_cost_usd=.02,
    )
    assert report["status"] == "SKIPPED_NOT_EXPLICITLY_AUTHORIZED"
    assert report["n_http_calls"] == 0
    assert report["first_live_verified"] is False
    assert report["edl_modified"] is False


def test_one_model_semantic_prior_is_not_auto_insert(tmp_path, monkeypatch):
    def fake_video(*, source_mp4, begin, end, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(Path(source_mp4).read_bytes())
        return {"ok": True, "path": str(output), "sha256": "f" * 64}
    monkeypatch.setattr(m, "_source_context_video", fake_video)

    class Provider:
        calls = 0
        def chat(self, **kwargs):
            self.calls += 1
            messages = kwargs["messages"]
            videos = [
                x for x in messages[-1]["content"] if x.get("type") == "video_url"
            ]
            assert len(videos) == 2
            return {"provider_mode": "real", "content": json.dumps({
                "verdict": "SUPPORTS_ADDITION",
                "baseline_story_observation": "Baseline jumps between two distant game moments.",
                "candidate_video_observation": "Candidate shows a real pressure build-up close to the goal.",
                "specific_new_information": "The candidate explains a relevant possession progression.",
                "concrete_baseline_comparison": "This possession change is absent in the baseline edit.",
                "relative_second_in_baseline": 7.0,
                "relative_second_in_candidate": 4.0,
            })}
    provider = Provider()
    monkeypatch.setattr(m, "provider_usage", lambda api: {
        "http_attempts": api.calls, "est_cost_usd_real": 0.0,
    })
    report = m.review_additive_native_video(
        api=provider, pack=_pack(tmp_path),
        out_dir=tmp_path/"review", approved=True,
        max_calls=2, max_cost_usd=.02,
    )
    assert provider.calls == 1
    assert report["n_http_calls"] == 1
    assert report["status"] == "MODEL_SUGGESTS_ADDITIVE_NARRATIVE_PRIOR_ONLY"
    assert report["semantic_gain_confirmed"] is False
    assert report["first_live_verified"] is False
    assert report["edl_modified"] is False
    assert report["release_authorized"] is False


def test_shared_budget_blocks_native_call(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "provider_usage", lambda api: {
        "http_attempts": 3, "est_cost_usd_real": .04,
    })
    class DoNotCall:
        def chat(self, **kwargs):
            raise AssertionError("shared budget exceeded")
    out = m.review_additive_native_video(
        api=DoNotCall(), pack=_pack(tmp_path),
        out_dir=tmp_path/"blocked", approved=True,
        max_calls=3, max_cost_usd=.04,
    )
    assert out["status"] == "SKIPPED_SHARED_PROVIDER_BUDGET_EXHAUSTED"
    assert out["n_http_calls"] == 0
