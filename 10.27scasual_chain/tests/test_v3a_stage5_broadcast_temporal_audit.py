"""Stage5 no-HTTP regression tests for independent broadcast temporal evidence."""
from story_video_agent_v3.stage5_broadcast_temporal_audit import (
    _semantic_consensus,
    assess_score_transition,
)


def _r(t, score, status="ok"):
    return {"media_sec": t, "score_tuple": list(score), "status": status}


def test_score_flip_after_goal_is_corroboration_not_first_live():
    rows = [
        _r(6439, (0, 1)), _r(6443, (0, 1)),
        _r(6459, (1, 1)), _r(6461, (1, 1)),
    ]
    got = assess_score_transition(
        ocr_rows=rows, score_before=(0, 1), score_after=(1, 1),
        shot_sec=6447.2, net_sec=6450.6, replay_overlap=False,
    )
    assert got["status"] == "SCORE_TRANSITION_CORROBORATED"
    assert got["ready_for_broadcast_review"]
    assert got["first_live_verified"] is False
    assert got["first_strong_after_sec"] == 6459


def test_weak_ocr_cannot_promote_video_transition():
    rows = [
        _r(6439, (0, 1), "weak"), _r(6443, (0, 1), "weak"),
        _r(6459, (1, 1), "weak"), _r(6461, (1, 1), "weak"),
    ]
    got = assess_score_transition(
        ocr_rows=rows, score_before=(0, 1), score_after=(1, 1),
        shot_sec=6447, net_sec=6450, replay_overlap=False,
    )
    assert got["status"] == "SCORE_TRANSITION_INSUFFICIENT_OCR"
    assert not got["ready_for_broadcast_review"]


def test_replay_overlap_always_blocks_even_when_scoreboard_flips():
    rows = [_r(6439, (0, 1)), _r(6443, (0, 1)),
            _r(6459, (1, 1)), _r(6461, (1, 1))]
    got = assess_score_transition(
        ocr_rows=rows, score_before=(0, 1), score_after=(1, 1),
        shot_sec=6447, net_sec=6450, replay_overlap=True,
    )
    assert got["status"] == "REPLAY_EVENT_CONFLICT"
    assert not got["ready_for_broadcast_review"]


def test_score_after_before_shot_is_conflict():
    rows = [_r(6438, (1, 1)), _r(6439, (0, 1)),
            _r(6443, (0, 1)), _r(6459, (1, 1)), _r(6461, (1, 1))]
    got = assess_score_transition(
        ocr_rows=rows, score_before=(0, 1), score_after=(1, 1),
        shot_sec=6447, net_sec=6450, replay_overlap=False,
    )
    assert got["status"] == "SCORE_ORDER_CONFLICT"


def test_model_agreement_is_not_merged_video_continuity():
    obs = [
        {"shot_sec": 6447.2, "net_sec": 6450.6,
         "shot_frame_ids": ["a"], "net_frame_ids": ["b"],
         "log_sha256": "a" * 64},
        {"shot_sec": 6447.88, "net_sec": 6449.68,
         "shot_frame_ids": ["c"], "net_frame_ids": ["d"],
         "log_sha256": "b" * 64},
    ]
    got = _semantic_consensus(obs)
    assert got["agreed"] is True
    assert got["n_observations"] == 2
    assert got["shot_sec"] == 6447.2
    assert got["net_sec"] == 6450.6
    # No field in this model agreement function is FIRST_LIVE_VERIFIED.
    assert "first_live_verified" not in got


def test_one_uncited_model_is_not_two_independent_observations():
    obs = [
        {"shot_sec": 6447, "net_sec": 6450,
         "shot_frame_ids": ["a"], "net_frame_ids": ["b"]},
        {"shot_sec": 6447, "net_sec": 6450,
         "shot_frame_ids": [], "net_frame_ids": ["d"]},
    ]
    assert not _semantic_consensus(obs)["agreed"]
