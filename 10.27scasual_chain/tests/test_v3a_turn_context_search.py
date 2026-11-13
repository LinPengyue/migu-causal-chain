"""Pure offline tests for turning-point context search (no video/paid API)."""
from story_video_agent_v3.story_turn_context_search import propose_turning_point_context


def row(sid, role, a, b):
    return {"segment_id":sid, "role":role,"media_in":a,"media_out":b,
            "include_in_cut":True}


def ev(eid, t, a=None, b=None, phase="LIVE"):
    return {"event_id":eid,"event_type":"shot",
            "media_time":{"start_time_sec":t-3 if a is None else a,
                          "event_time_sec":t,
                          "end_time_sec":t+3 if b is None else b},
            "video_context":{"broadcast_phase":phase}}


def test_near_turn_and_goal_protection():
    edl=[row("setup","deficit_scoreboard_anchor",100,104),
         row("buildup","buildup_action",500,512),
         row("equalizer","equalizer_goal_action",700,722),
         row("score","equalizer_scoreboard_anchor",735,739)]
    events=[ev("too_early",400),ev("good",680),ev("duplicate",681),
            ev("in_goal",707),ev("replay",690,phase="REPLAY")]
    out=propose_turning_point_context(edl=edl,events=events,lookback_sec=180)
    assert out["mode"]=="OBSERVATION_ONLY"
    assert out["first_live_certified"] is False
    t=out["targets"][0]
    assert t["source_search_interval"]==[518.0,698.0]
    assert [c["event_id"] for c in t["ranked_event_probes"]]==["good"]
    assert t["candidate_action_authorized"] is False
    assert all(c["first_live_status"]=="UNRESOLVED" for c in t["ranked_event_probes"])


def test_no_turn_or_insufficient_gap():
    assert propose_turning_point_context(edl=[row("b","buildup_action",100,120)],
                                         events=[])["targets"]==[]
    close=[row("b","buildup_action",100,110),
           row("goal","equalizer_goal_action",115,137)]
    assert propose_turning_point_context(edl=close,events=[])["targets"]==[]


def test_no_event_still_supports_review_without_false_positive():
    edl=[row("b","buildup_action",100,120),
         row("t","equalizer_goal_action",350,372)]
    t=propose_turning_point_context(edl=edl,events=[])["targets"][0]
    assert t["ranked_event_probes"]==[]
    assert t["fallback_observation_interval"][0]<t["fallback_observation_interval"][1]
    assert t["requires_video_semantics"] is True
    assert t["requires_first_live_before_insert"] is True


def test_match_agnostic_same_behavior_on_other_time_axis():
    edl=[row("b","buildup_action",1100,1112),
         row("t","equalizer_goal_action",2300,2322)]
    result=propose_turning_point_context(
        edl=edl,events=[ev("near_turn",2290),ev("far_away",1300)])
    assert [c["event_id"] for c in result["targets"][0]["ranked_event_probes"]]==["near_turn"]
