"""Zero-HTTP fixtures: exercise the exact loop with synthetic backend responses."""
import unittest
from copy import deepcopy
from pathlib import Path
import tempfile
from general_agent_protocol import (seed_rows,task_windows,parse_hypotheses,validate_observation,
    trial_revision,verifier_decision,story_intervals,cut_identity)
from general_story_agent import run_agent

E={"video_id":"v","duration_sec":500,"input_tier":"RAW_EVENTS_ONLY","atoms":{},
   "chains":{},"teams":{"team_1":{"name":"A"},"team_2":{"name":"B"}}}
G={"video_id":"v","input_tier":"RAW_EVENTS_ONLY","story_id":"equalization:1",
   "template_id":"equalization","category":"test","subtype":"test","narrative_goal":["draw level"],
   "subjects":["team_1"],"edges":[],"diagnostics":[],
   "agent_seed":{"file":"initial_edl.json"},
   "nodes":[{"node_id":"a","node_type":"anchor","required":True,"event_ids":[],"media_windows":[[10,20]]},
            {"node_id":"b","node_type":"missing","required":True,"event_ids":[],"media_windows":[],
             "score":"1:1","action_time_interval":[100,200],"observation_task_ids":["missing"]}]}
R={"segment_id":"s","media_in":10,"media_out":20,"story_node_ids":["a"],"event_ids":[]}
T={"task_id":"missing","task_type":"missing_goal_localization","video_id":"v",
   "score_beneficiary":"team_1","search_interval":[100,200],"questions":["find goal"],"event_ids":[]}
O={"finding":"SUPPORTED","broadcast":"LIVE","source_window":[100,140],"action_window_sec":[110,120],
   "event_ids":[],"story_node_ids":["b"]}
P={"action":"add","observation_id":"obs:1"}

class ProtocolTests(unittest.TestCase):
    def test_tiles_cover_full_interval(self):
        ws=task_windows(T,E,40)
        self.assertEqual(ws[0][0],100); self.assertEqual(ws[-1][1],200)
        self.assertTrue(all(a[1]>=b[0] for a,b in zip(ws,ws[1:])))
    def test_legacy_scoreboard_is_not_action_preview(self):
        g=deepcopy(G); g["agent_seed"]["file"]="legacy_seed.json"
        legacy={"edl":[{**R,"shot_kind":"live","include_in_cut":False},
                       {"segment_id":"board","shot_kind":"scoreboard_anchor","media_in":30,"media_out":34}]}
        r=seed_rows(g,[],legacy,E)
        self.assertEqual(len(r),1); self.assertTrue(r[0]["preview_only"])
        self.assertFalse(r[0]["first_live_verified"])
    def test_hypothesis_unknown_id_rejected(self):
        with self.assertRaises(ValueError):
            parse_hypotheses({"hypotheses":[{"event_ids":["fabricated"],"hypothesis":"x",
                "narrative_function":"y"}]},{"interval_id":"i"},[])
    def test_short_story_tail_not_unbounded(self):
        self.assertFalse(any(x["interval_id"].startswith("tail") for x in story_intervals(G,E)))
    def test_observation_outside_clip_rejected(self):
        with self.assertRaises(ValueError):
            validate_observation({"clip_id":"c","finding":"SUPPORTED","description":"goal",
                                  "action_window_sec":[90,120]},
                                 {"clip_id":"c","source_window":[100,140],"sha256":"x"},"s",500)
    def test_missing_goal_trial_bound(self):
        new=trial_revision([R],P,{"obs:1":O},E,[])
        self.assertEqual(cut_identity(new),((10,20),(110,120)))
        self.assertEqual(new[-1]["story_node_ids"],["b"])
        self.assertFalse(new[-1]["first_live_verified"])
    def test_replay_overlap_rejected(self):
        with self.assertRaises(ValueError):
            trial_revision([R],P,{"obs:1":O},E,[[115,118]])
    def test_uncertain_or_text_only_never_accept(self):
        self.assertEqual(verifier_decision({"decision":"ACCEPT"},True,False),"NOT_EVALUATED")
        with self.assertRaises(ValueError):
            verifier_decision({"decision":"ACCEPT","rationale":"better"},True,True)
    def test_protected_anchor_not_replaced_by_unrelated_clip(self):
        with self.assertRaises(ValueError):
            trial_revision([R],{"action":"replace","observation_id":"obs:1","target_segment_id":"s"},
                           {"obs:1":O},E,[])
    def test_reject_overlap(self):
        obs={**O,"action_window_sec":[15,25],"source_window":[10,30]}
        with self.assertRaises(ValueError):
            trial_revision([R],P,{"obs:1":obs},E,[])

class FakeBackend:
    # This fake exercises control flow only. No video or model has run.
    real_visual=False
    source_sha="fixture"
    max_clip_sec=40
    def __init__(self): self.calls=[]
    def calls_left(self): return 100
    def usage(self): return {"http_attempts":0}
    def render_preview(self,rows,out,clip_id):
        return {"clip_id":clip_id,"path":str(out),"story_range_sec":[0,10],"sha256":"fixture"}
    def observe_clip(self,w,out,clip_id):
        return {"clip_id":clip_id,"path":str(out),"source_window":w,"sha256":"fixture"}
    def query(self,stage,prompt,d,clips=()):
        self.calls.append(stage)
        if stage=="critic": return {"action":"investigate","issue":"missing goal","interval_id":None}
        if stage=="plan_observation": return {"action":"observe","target_id":"missing:tile:1"}
        if stage=="observe": return {"clip_id":"source:1","finding":"SUPPORTED","description":"fixture goal",
            "broadcast":"LIVE","action_window_sec":[110,120],"goal_visible":True,"goal_beneficiary":"team_1"}
        if stage=="plan_revision": return {"action":"add","observation_id":"obs:1","rationale":"fixture"}
        if stage=="verify": return {"decision":"ACCEPT","rationale":"fixture","original_issue_resolved":True,
            "new_defect":False,"before_evidence":"fixture before","after_evidence":"fixture after"}
        raise AssertionError(stage)

class LoopTests(unittest.TestCase):
    def test_full_fixture_loop_never_claims_real_accept(self):
        prepared={"graph":G,"seed_edl":[R],"tasks":[T],"intervals":[],"nonlive_windows":[],
            "targets":[{"target_id":"missing:tile:1","task":T,"type":T["task_type"],
                        "source_window":[100,140],"event_ids":[]}]}
        backend=FakeBackend()
        with tempfile.TemporaryDirectory() as d:
            report=run_agent(prepared,E,backend,Path(d),max_rounds=1)
            self.assertEqual(backend.calls,["critic","plan_observation","observe","plan_revision","verify"])
            self.assertEqual(report["rounds"][0]["decision"],"NOT_EVALUATED")
            self.assertFalse(report["changed"])
            self.assertTrue(report["fixture_only"])
            self.assertEqual(report["n_accepted"],0)
            self.assertTrue((Path(d)/"round_01"/"trial_edl.json").is_file())

    def test_simulated_visual_accept_updates_missing_node(self):
        # Only a contract simulation: no real images or provider call.
        backend=FakeBackend()
        backend.real_visual=True
        prepared={"graph":G,"seed_edl":[R],"tasks":[T],"intervals":[],"nonlive_windows":[],
            "targets":[{"target_id":"missing:tile:1","task":T,"type":T["task_type"],
                        "source_window":[100,140],"event_ids":[]}]}
        with tempfile.TemporaryDirectory() as d:
            from template_graph import read
            report=run_agent(prepared,E,backend,Path(d),max_rounds=1)
            self.assertEqual(report["n_accepted"],1)
            self.assertTrue(report["changed"])
            node=read(Path(d)/"refined_story_graph.json")["nodes"][1]
            self.assertEqual(node["localization_status"],"video_supported_candidate")
            self.assertEqual(node["active_segment_ids"],["trial:obs:1"])
            self.assertFalse(report["first_live_verified"])

    def test_simulated_reject_feeds_next_critic_and_keeps_seed(self):
        class RejectBackend(FakeBackend):
            real_visual=True
            def query(self,stage,prompt,d,clips=()):
                if stage=="verify":
                    self.calls.append(stage)
                    return {"decision":"REJECT","rationale":"insertion disrupts story"}
                if stage=="critic" and self.calls:
                    self.calls.append(stage)
                    self.feedback_seen="insertion disrupts story" in prompt
                    return {"action":"keep","issue":"no better alternative"}
                return super().query(stage,prompt,d,clips)
        backend=RejectBackend()
        prepared={"graph":G,"seed_edl":[R],"tasks":[T],"intervals":[],"nonlive_windows":[],
            "targets":[{"target_id":"missing:tile:1","task":T,"type":T["task_type"],
                        "source_window":[100,140],"event_ids":[]}]}
        with tempfile.TemporaryDirectory() as d:
            report=run_agent(prepared,E,backend,Path(d),max_rounds=2)
            self.assertEqual(report["rounds"][0]["decision"],"REJECT")
            self.assertTrue(backend.feedback_seen)
            self.assertFalse(report["changed"])
            self.assertEqual(report["n_accepted"],0)

    def test_complete_story_can_stop_without_trial(self):
        class KeepBackend(FakeBackend):
            def query(self,stage,prompt,d,clips=()):
                self.calls.append(stage)
                return {"action":"keep","issue":"no worthwhile improvement"}
        g=deepcopy(G); g["nodes"]=g["nodes"][:1]
        prepared={"graph":g,"seed_edl":[R],"tasks":[],"intervals":[],"nonlive_windows":[],"targets":[]}
        backend=KeepBackend()
        with tempfile.TemporaryDirectory() as d:
            report=run_agent(prepared,E,backend,Path(d),max_rounds=2)
            self.assertEqual(backend.calls,["critic"])
            self.assertFalse(report["changed"])
            self.assertEqual(report["stop_reason"],"critic_no_worthwhile_change")


if __name__=="__main__":
    unittest.main()
