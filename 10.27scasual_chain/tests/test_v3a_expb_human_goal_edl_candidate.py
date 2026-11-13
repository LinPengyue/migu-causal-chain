import pytest
from story_video_agent_v3.expb_human_goal_edl_candidate import make_proposal

SHA = "a" * 64
ISSUE = "goal_coverage_01_to_11"


def attested():
    return {"human_confirmed_first_live": True, "source_sha256": SHA,
            "issue_id": ISSUE, "reviewer_confirmation": "Reviewed original continuous broadcast"}


def edl():
    return {"segments": [
        {"segment_id": "before", "role": "setup", "media_in": 6300, "media_out": 6320},
        {"segment_id": "after", "role": "ending", "media_in": 6600, "media_out": 6620},
    ]}


def propose(**kw):
    return make_proposal(edl=kw.pop("edl", edl()),
                         attestation=kw.pop("attestation", attested()),
                         source_sha=SHA, issue_id=ISSUE,
                         shot=6447.88, net=6450.6, **kw)


def test_proposal_only_and_no_gate_upgrade():
    p = propose()
    assert p["proposed_segment"]["media_in"] == 6441.88
    assert p["proposed_segment"]["media_out"] == 6459.6
    assert p["placement_status"] == "CHRONOLOGICAL_NEIGHBORS"
    assert p["suggested_insert_after_segment_id"] == "before"
    assert p["suggested_insert_before_segment_id"] == "after"
    assert not p["first_live_verified"] and not p["executable_safe_revision"]
    assert not p["edl_modified"] and p["api_calls"] == 0


def test_attestation_required():
    a = attested()
    a["human_confirmed_first_live"] = False
    with pytest.raises(ValueError, match="attestation_required"):
        propose(attestation=a)


def test_wrong_source_rejected():
    a = attested()
    a["source_sha256"] = "wrong"
    with pytest.raises(ValueError, match="source_sha_mismatch"):
        propose(attestation=a)


def test_overlap_rejected():
    rows = edl()
    rows["segments"].append({"segment_id": "duplicate", "media_in": 6445, "media_out": 6452})
    with pytest.raises(ValueError, match="overlaps_existing"):
        propose(edl=rows)


def test_invalid_window_rejected():
    with pytest.raises(ValueError, match="invalid_goal_or_clip_window"):
        propose(pre_sec=100)
