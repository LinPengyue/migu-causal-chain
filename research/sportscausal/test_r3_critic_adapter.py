"""Zero-HTTP tests; no semantic/video success claimed."""
import json
import unittest
from copy import deepcopy
from test_r3_legacy_agent_adapter import fixture
from r3_legacy_agent_adapter import adapt
from r3_critic_adapter import scope_diagnosis, planner_view, protect_planner_intents

def native_issues():
    return {"issues":[
        {"issue_id":"goal_coverage_00_to_01","category":"goal_coverage","score_before":[0,0],"score_after":[0,1]},
        {"issue_id":"goal_coverage_01_to_11","category":"goal_coverage","score_before":[0,1],"score_after":[1,1]},
        {"issue_id":"goal_coverage_11_to_21","category":"goal_coverage","score_before":[1,1],"score_after":[2,1]},
        {"issue_id":"sparse_pre_turn_bridge","category":"buildup"},
        {"issue_id":"replay_flagged_s1","category":"replay_risk"},
        {"issue_id":"missing_source_video_ref","category":"input_integrity"}],
        "protected_goal_segment_ids":[]}

class CriticAdapterTests(unittest.TestCase):
    def test_essential_context_survives_legacy_sorted_json_cap(self):
        g,r,e,events=fixture()
        b=adapt(g,r,None,[],[],e,events)
        plan=b["plan"]; plan["candidate_edl"]=[{"padding":"x"*20000}]
        s=json.dumps(plan,ensure_ascii=False,sort_keys=True)[:9000]
        prefix='{"a_story_template_context": '
        self.assertTrue(s.startswith(prefix))
        obj,_=json.JSONDecoder().raw_decode(s[len(prefix):])
        self.assertEqual(obj,plan["a_story_template_context"])
        self.assertEqual(obj["narrative_goal"],g["narrative_goal"])

    def test_keeper_no_unrelated_match_goals_or_comeback_heuristics(self):
        g,r,e,events=fixture()
        plan=adapt(g,r,None,[],[],e,events)["plan"]
        d=native_issues(); before=deepcopy(d)
        s=scope_diagnosis(d,plan,r)
        self.assertEqual([i["issue_id"] for i in s["issues"]],
                         ["replay_flagged_s1","missing_source_video_ref"])
        self.assertEqual(s["protected_story_segment_ids"],["s1","s2"])
        self.assertEqual(d,before)

    def test_goal_scope_only_actual_transition_and_missing_task(self):
        g,r,e,events=fixture()
        g["template_id"]="equalization"
        g["nodes"][0].update(kind="score_state",state_sign=-1,score="0:1",
           goal_roles=[{"score_binding":{"score_before":"0:0","score_after":"0:1",
                                        "confirmation_t_sec":20,"action_t_sec":11,"event_id":"a"}}])
        g["nodes"][1].update(node_type="missing",kind="score_state",state_sign=0,score="1:1",
            media_windows=[],event_ids=[],observation_task_ids=["t"])
        t={"task_id":"t","video_id":"v","task_type":"missing_goal_localization",
           "score_before":"0:1","score_after":"1:1","confirmation_t_sec":130,
           "search_interval":[90,145]}
        b=adapt(g,r[:1],None,[t],[],e,events)
        d=native_issues()
        d["issues"].append({"issue_id":"insufficient_media_segments","category":"arc_coverage"})
        s=scope_diagnosis(d,b["plan"],b["edl"])
        goals=[i for i in s["issues"] if i["category"]=="goal_coverage"]
        self.assertEqual([i["issue_id"] for i in goals],
                         ["goal_coverage_00_to_01","goal_coverage_01_to_11"])
        self.assertEqual(goals[-1]["r3_goal_target"]["task_id"],"t")
        self.assertNotIn("insufficient_media_segments",[i["issue_id"] for i in s["issues"]])

    def test_missing_native_issue_reported_not_fabricated(self):
        g,r,e,events=fixture()
        g["nodes"][1].update(node_type="missing",media_windows=[],event_ids=[],
                             observation_task_ids=["t"])
        t={"task_id":"t","video_id":"v","task_type":"missing_goal_localization",
           "score_before":"0:1","score_after":"1:1","confirmation_t_sec":130,
           "search_interval":[90,145]}
        b=adapt(g,r[:1],None,[t],[],e,events)
        s=scope_diagnosis({"issues":[]},b["plan"],b["edl"])
        self.assertEqual(s["issues"],[])
        self.assertEqual(s["r3_scope_audit"]["missing_goal_tasks_without_native_issue"][0]["task_id"],"t")

    def test_planner_only_protection_does_not_modify_goal_ids(self):
        d={"r3_story_context":{},"protected_goal_segment_ids":["goal"],
           "protected_story_segment_ids":["save","goal"]}
        p=planner_view(d)
        self.assertEqual(p["protected_goal_segment_ids"],["goal","save"])
        self.assertEqual(d["protected_goal_segment_ids"],["goal"])

    def test_legacy_identity(self):
        d=native_issues()
        self.assertIs(scope_diagnosis(d,{"template_id":"T01_comeback"},[]),d)
        self.assertIs(planner_view(d),d)
        self.assertIs(protect_planner_intents(d,d,None),d)

    def test_comeback_heuristics_preserved(self):
        g,r,e,events=fixture()
        g["template_id"]="comeback"
        b=adapt(g,r,None,[],[],e,events,seed="r3")
        s=scope_diagnosis(native_issues(),b["plan"],b["edl"])
        self.assertIn("sparse_pre_turn_bridge",[i["issue_id"] for i in s["issues"]])

if __name__=="__main__":
    unittest.main()
