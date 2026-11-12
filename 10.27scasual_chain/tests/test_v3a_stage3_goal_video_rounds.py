"""Stage3 P13 video-observation regressions (zero HTTP).

Tests selection and adaptive sampling policy, not football action accuracy
or first-live verification. No truth/reference EDL, timestamps or paid API.
"""
from story_video_agent_v3.remote_vlm_verify import (
    _goal_video_round_evidence_complete,
    _goal_video_round_rank,
)


def _round(*, shot, net, shot_ids=(), net_ids=(), live="live",
           team=True, continuity=True, uncertain=(), ok=True):
    return {
        "ok": ok,
        "provider_mode": "real",
        "vlm_inference": {
            "observed_shot": shot,
            "observed_net": net,
            "shot_frame_ids": list(shot_ids),
            "net_frame_ids": list(net_ids),
            "live_or_replay": live,
            "attacking_team_match": team,
            "claims_continuous_live": continuity,
            "uncertain": list(uncertain),
        },
    }


def test_net_only_first_round_requires_more_video():
    first = _round(shot=False, net=True, net_ids=("f7",))
    assert not _goal_video_round_evidence_complete(first)
    second = _round(shot=True, net=True, shot_ids=("f2",), net_ids=("f5",))
    assert _goal_video_round_evidence_complete(second)
    assert _goal_video_round_rank(second) > _goal_video_round_rank(first)


def test_shot_net_claims_without_citations_are_not_complete():
    uncited = _round(shot=True, net=True)
    assert not _goal_video_round_evidence_complete(uncited)
    cited = _round(shot=True, net=True, shot_ids=("s",), net_ids=("n",))
    assert _goal_video_round_evidence_complete(cited)


def test_positive_replay_or_uncertain_clip_still_requires_review():
    cited_replay = _round(
        shot=True, net=True, shot_ids=("s",), net_ids=("n",), live="replay",
    )
    cited_uncertain = _round(
        shot=True, net=True, shot_ids=("s",), net_ids=("n",),
        uncertain=("could_be_replay",),
    )
    assert not _goal_video_round_evidence_complete(cited_replay)
    assert not _goal_video_round_evidence_complete(cited_uncertain)


def test_one_complete_video_round_outweighs_two_incompatible_partials():
    # Model may see the shot in one run and net in another. The system MUST
    # NOT merge their frame IDs into a fictional continuous-video observation.
    shot_only = _round(shot=True, net=False, shot_ids=("s",))
    net_only = _round(shot=False, net=True, net_ids=("n",))
    assert not _goal_video_round_evidence_complete(shot_only)
    assert not _goal_video_round_evidence_complete(net_only)
    best = max([shot_only, net_only], key=_goal_video_round_rank)
    assert not _goal_video_round_evidence_complete(best)


def test_failed_response_cannot_beat_successful_partial():
    fake_fail = _round(shot=True, net=True, shot_ids=("s",),
                       net_ids=("n",), ok=False)
    shot = _round(shot=True, net=False, shot_ids=("s",))
    assert not _goal_video_round_evidence_complete(fake_fail)
    assert _goal_video_round_rank(shot) > _goal_video_round_rank(fake_fail)
