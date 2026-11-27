import unittest
from copy import deepcopy
from r3_legacy_agent_adapter import adapt, validate_source_events, _role

def fixture():
    e={"video_id":"v","input_tier":"RAW_EVENTS_ONLY","duration_sec":300,
       "teams":{"team_1":{"name":"A"},"team_2":{"name":"B"}},"chains":{},
       "atoms":{"a":{"event_id":"a","t":11,"window":[10,12]},
                "b":{"event_id":"b","t":101,"window":[100,102]}}}
    events=[{"event_id":eid,"media_time":{"event_time_sec":a["t"],
             "start_time_sec":a["window"][0],"end_time_sec":a["window"][1]},
             "video_context":{"broadcast_phase":"LIVE"}} for eid,a in e["atoms"].items()]
    g={"schema":"sportscausal_story_graph_v1","video_id":"v","input_tier":"RAW_EVENTS_ONLY",
       "story_id":"keeper_rescue:1","template_id":"keeper_rescue","category":"character",
       "subtype":"keeper rescues","narrative_goal":["repeated rescue"],"subjects":["team_1"],
       "first_live_verified":False,"release_authorized":False,
       "agent_seed":{"file":"initial_edl.json"},
       "nodes":[{"node_id":"a1","node_type":"anchor","required":True,"predicate":"goalkeeper_rescue",
                 "actor":"team_1","event_ids":["a"],"media_windows":[[10,12]],"anchor_t":11},
                {"node_id":"a2","node_type":"anchor","required":True,"predicate":"goalkeeper_rescue",
                 "actor":"team_1","event_ids":["b"],"media_windows":[[100,102]],"anchor_t":101}]}
    rows=[{"segment_id":sid,"media_in":a["window"][0],"media_out":a["window"][1],
           "event_ids":[eid],"story_node_ids":[nid]} for sid,eid,nid,a in
          [("s1","a","a1",e["atoms"]["a"]),("s2","b","a2",e["atoms"]["b"])]]
    return g,rows,e,events

class AdapterTests(unittest.TestCase):
    def test_keeper_anchor_roles_not_fabricated_goals(self):
        g,r,e,events=fixture()
        b=adapt(g,r,None,[],[],e,events)
        self.assertEqual([x["role"] for x in b["edl"]],["goalkeeper_rescue"]*2)
        self.assertTrue(all(x["story_anchor"] for x in b["edl"]))
        self.assertEqual(b["duration_sec"],4)
    def test_required_context_not_a_new_anchor(self):
        g,r,e,events=fixture()
        g["nodes"][1]["node_type"]="context"
        b=adapt(g,r,None,[],[],e,events)
        self.assertTrue(b["edl"][0]["story_anchor"])
        self.assertFalse(b["edl"][1]["story_anchor"])
        self.assertEqual(b["edl"][1]["required_story_node_ids"],["a2"])
    def test_missing_node_no_virtual_media(self):
        g,r,e,events=fixture()
        g["nodes"][1].update(node_type="missing",media_windows=[],event_ids=[],
                            observation_task_ids=["t"])
        b=adapt(g,r[:1],None,[{"task_id":"t","video_id":"v"}],[],e,events)
        self.assertEqual(len(b["edl"]),1)
        self.assertEqual(b["missing"][0]["node"]["node_id"],"a2")
        self.assertEqual(b["missing"][0]["tasks"][0]["task_id"],"t")
    def test_legacy_preserve_native_action_windows(self):
        g,r,e,events=fixture()
        g["template_id"]="comeback"
        g["agent_seed"]["file"]="legacy_seed.json"
        old={"edl":[{**r[0],"media_in":8,"media_out":14,"shot_kind":"live",
                     "role":"opponent_opening_goal_action","include_in_cut":False},
                    {"segment_id":"board","media_in":20,"media_out":23,
                     "shot_kind":"scoreboard_anchor","role":"scoreboard"},
                    {**r[1],"media_in":98,"media_out":104,"shot_kind":"live",
                     "role":"equalizer_goal_action","include_in_cut":False}]}
        before=deepcopy(old)
        b=adapt(g,r,old,[],[],e,events)
        self.assertEqual(old,before)
        self.assertEqual([(x["media_in"],x["media_out"]) for x in b["edl"]],[(8,14),(98,104)])
        self.assertFalse(b["plan"]["render_ready"])
    def test_native_event_time_mismatch(self):
        g,r,e,events=fixture()
        validate_source_events(e,events)
        events[0]["media_time"]["event_time_sec"]=11.5
        with self.assertRaises(ValueError):
            validate_source_events(e,events)
    def test_nonlive_legacy_overlap_visible_not_silently_trimmed(self):
        g,r,e,events=fixture()
        events.append({"event_id":"rep","media_time":{"event_time_sec":11.5,
                       "start_time_sec":11,"end_time_sec":12},
                       "video_context":{"broadcast_phase":"REPLAY"}})
        b=adapt(g,r,None,[],[],e,events)
        self.assertEqual(b["annotated_nonlive_overlaps"],[{"segment_id":"s1","replay_event_ids":["rep"]}])
        self.assertEqual(b["edl"][0]["media_in"],10)
    def test_representative_anchor_no_duplicate_semantic_anchor(self):
        g,r,e,events=fixture()
        g["nodes"]=g["nodes"][:1]
        r[1]["story_node_ids"]=["a1"]
        b=adapt(g,r,None,[],[],e,events)
        self.assertEqual(sum(x["story_anchor"] for x in b["edl"]),1)
        self.assertEqual(b["anchor_bindings"][0]["all_segment_ids"],["s1","s2"])
    def test_inputs_unchanged(self):
        g,r,e,events=fixture()
        before=deepcopy((g,r,e,events))
        adapt(g,r,None,[],[],e,events)
        self.assertEqual((g,r,e,events),before)

    def test_lead_roles_from_bound_score_changes(self):
        g,r,e,events=fixture()
        g["template_id"]="lead_preservation"
        def node(i,before,after,beneficiary,subject,eid):
            return {"kind":"score_state","node_type":"anchor","state_sign":1,
                    "score_path_index":i,"score":after,"actor":subject,
                    "event_ids":[eid],"goal_roles":[{"score_binding":{
                        "path_index":i,"score_before":before,"score_after":after,
                        "score_beneficiary":beneficiary,"event_id":eid}}]}
        for idx,(before,after) in enumerate([("0:0","0:1"),("0:1","0:2")]):
            eid=["a","b"][idx]
            g["nodes"][idx].update(node(idx+1,before,after,"team_2","team_2",eid))
        g["subjects"]=["team_2"]
        b=adapt(g,r,None,[],[],e,events)
        expected=["go_ahead_goal_action","lead_extend_2_goal_action"]
        self.assertEqual([x["role"] for x in b["edl"]],expected)
        self.assertEqual([x["role"] for x in b["plan"]["beats"]],expected)
        self.assertEqual([x["role"] for x in b["plan"]["agent_story_context"]["required_nodes"]],expected)
        self.assertEqual([(x["media_in"],x["media_out"],x["event_ids"]) for x in b["edl"]],
                         [(x["media_in"],x["media_out"],x["event_ids"]) for x in r])
        # A further lead extension is a different scoring transition, not
        # the same goal duplicated. A later opposition score narrows the lead.
        self.assertEqual(_role(node(3,"0:2","0:3","team_2","team_2","c"),"lead_preservation"),
                         "lead_extend_3_goal_action")
        self.assertEqual(_role(node(4,"0:3","1:3","team_1","team_2","d"),"lead_preservation"),
                         "opponent_reduce_lead_4_goal_action")
        # Scoreboard column orientation follows the observed increment,
        # not a hardcoded team_1=left assumption.
        self.assertEqual(_role(node(3,"2:0","3:0","team_2","team_2","c"),"lead_preservation"),
                         "lead_extend_3_goal_action")
        self.assertEqual(_role(g["nodes"][1],"comeback"),"go_ahead_goal_action")
        wrong=deepcopy(g["nodes"][1])
        wrong["goal_roles"][0]["score_binding"]["event_id"]="not_b"
        with self.assertRaises(ValueError):
            _role(wrong,"lead_preservation")

if __name__=="__main__":
    unittest.main()
