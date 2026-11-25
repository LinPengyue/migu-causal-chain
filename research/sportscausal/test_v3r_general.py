import unittest
from semantic_normalization import normalize
from temporal_patterns import match

TEAMS={"team_1":{"name":"甲队"},"team_2":{"name":"乙队"}}
def atom(i,t,note,typ="Save",attrs=None,window=None,phase="LIVE"):
    return {"event_id":i,"t":t,"window":window or [t-1,t+1],"notes":note,
            "type":typ,"attributes":attrs or {},"broadcast_phase":phase}
def evidence(*atoms):
    return {"schema":"sportscausal_evidence_v2","video_id":"v","input_tier":"RAW_EVENTS_ONLY",
            "teams":TEAMS,"atoms":{a["event_id"]:a for a in atoms},"chains":{}}
def template(op="repeat",pred="goalkeeper_rescue",lo=2):
    return {"template_id":"test","category":"test","subtype":"test","narrative_goal":["test"],
            "pattern":{"operator":op,"predicate":pred,"min_occurrences":lo}}

class RTests(unittest.TestCase):
    def test_actor_not_first_team_mention(self):
        e=evidence(atom("a",10,"面对1队球员的传中球，2队守门员给扑飞"),
                   atom("b",20,"2队球员发出的角球被1队守门员接住","Defensive_action",
                        {"Attacker":["2队球员"],"Defender":["1队守门员"]}),
                   atom("c",30,"2队守门员扑住了1队队员的打门"))
        s=normalize(e)["atoms"]
        self.assertEqual([x["keeper"]["team"] for x in s],["team_2","team_1","team_2"])
        self.assertEqual(s[2]["attacking_team"]["team"],"team_1")

    def test_player_conflict_not_team_conflict(self):
        a=atom("a",10,"2队3号守门员在禁区将球解围踢走","Defensive_action",
               {"Defender":["team_2_player_13"]})
        s=normalize(evidence(a))["atoms"][0]["keeper"]
        self.assertEqual(s["team"],"team_2")
        self.assertIsNone(s["player_number"])
        self.assertEqual(s["player_status"],"CONFLICT")

    def test_team_conflict_and_nonaction(self):
        e=evidence(atom("a",10,"2队守门员扑救","Defensive_action",{"Defender":["1队守门员"]}),
                   atom("b",20,"2队球员截获1队守门员的传球","Defensive_action",{"Defender":["2队球员"]}),
                   atom("c",30,"2队守门员扑救失败"),atom("d",40,""),
                   atom("e",50,"2队守门员扑救",phase="REPLAY"))
        s=normalize(e)["atoms"]
        self.assertEqual(s[0]["keeper"]["team_status"],"CONFLICT")
        self.assertTrue(all(not x["predicates"] for x in s))

    def test_keeper_possessive_and_passive_not_actor(self):
        e=evidence(atom("a",10,"2队守门员的传球被截获","Defensive_action"),
                   atom("b",20,"2队守门员被对方球员拦截","Defensive_action"))
        self.assertTrue(all(not x["predicates"] for x in normalize(e)["atoms"]))

    def test_repeat_multiple_subjects_overlap(self):
        e=evidence(atom("a",10,"甲队守门员扑救"),atom("b",10.5,"甲队门将接住球"),
                   atom("c",20,"1队守门员扑救"),atom("d",30,"2队门将扑救"),
                   atom("e",40,"2队守门员扑救"))
        r=match(template(),normalize(e),e)["candidates"]
        self.assertEqual([x["subjects"] for x in r],[["team_1"],["team_2"]])
        self.assertEqual([len(x["nodes"]) for x in r],[2,2])
        self.assertEqual(r[0]["nodes"][0]["event_ids"],["a","b"])

    def test_alternation_runs_not_single_switch(self):
        es=[atom(str(i),10*i+10,f"{side}队球员射门","Shot") for i,side in enumerate([1,1,2,2,1])]
        e=evidence(*es)
        r=match(template("alternate","attacking_threat",3),normalize(e),e)["candidates"]
        self.assertEqual([x["actor"] for x in r[0]["actor_runs"]],["team_1","team_2","team_1"])
        e=evidence(*es[:-1])
        self.assertEqual(match(template("alternate","attacking_threat",3),normalize(e),e)["candidates"],[])

    def test_predicted_chain_context_not_causal(self):
        e=evidence(atom("a",10,"2队守门员扑救"),atom("b",20,"2队守门员扑救"))
        e["chains"]={"p":{"chain_id":"p","state":"PARTIAL","available_event_ids":["a"]},
                     "r":{"chain_id":"r","state":"NONLIVE_CHAIN","available_event_ids":["a"]}}
        r=match(template(),normalize(e),e)["candidates"][0]
        self.assertEqual(r["nodes"][0]["chain_context_ids"],["p"])
        self.assertFalse(r["edges"][0]["causal_verified"])
        self.assertFalse(r["quality_verified"])


    def test_restart_and_goal_actor(self):
        e=evidence(atom("restart",10,"1队球员被罚角球，2队球员发角球","Corner_kick",
                        {"Related_Player":["2队球员"]}),
                   atom("goal",20,"2队9号头球破门","Goal"),
                   atom("cancelled",30,"2队9号进球无效","Goal"),
                   atom("unknown",40,"","Goal"))
        rows=normalize(e)["atoms"]
        self.assertEqual(rows[0]["predicates"]["set_piece_execution"]["actor"],"team_2")
        self.assertEqual(rows[1]["predicates"]["goal_action"]["actor"],"team_2")
        self.assertNotIn("goal_action",rows[2]["predicates"])
        self.assertNotIn("goal_action",rows[3]["predicates"])

    def test_relation_path_requires_actor_order_and_full_membership(self):
        e=evidence(atom("restart",10,"2队球员发角球","Corner_kick"),
                   atom("other",15,"1队球员发角球","Corner_kick"),
                   atom("goal",20,"2队9号头球破门","Goal"))
        def chain(ids,state="FULL",subtype="quick_restart_set_piece_chain"):
            return {"chain_id":"p","state":state,"subtype":subtype,"available_event_ids":ids}
        t=template()
        t["pattern"]={"operator":"relation_path","start_predicate":"set_piece_execution",
                      "end_predicate":"goal_action","chain_subtypes":["quick_restart_set_piece_chain"]}
        def run(c):
            e["chains"]={"p":c}
            return match(t,normalize(e),e)["candidates"]
        r=run(chain(["restart","goal"]))
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["subjects"],["team_2"])
        self.assertEqual(r[0]["edges"][0]["relation"],"predicted_chain_path_hypothesis")
        self.assertFalse(r[0]["edges"][0]["causal_verified"])
        self.assertEqual(run(chain(["restart","goal"],"PARTIAL")),[])
        self.assertEqual(run(chain(["restart","other","goal"])),[])
        self.assertEqual(run(chain(["goal","restart"])),[])
        self.assertEqual(run(chain(["restart","goal"],subtype="unrelated")),[])

    def test_state_pattern_uses_score_side_mapping_not_clip_times(self):
        e=evidence()
        t=template()
        t["pattern"]={"operator":"state_transition","signs":[-1,0,1],"terminal_sign":1,"selection":"last"}
        def row(i,score,delta=None):
            return {"t_sec":i*100,"score":score,"opening":i==0,"delta_side":delta,
                    "carrier_event_id":"carrier"+str(i)}
        doc={"video_id":"v","score_side_mapping":{"left":"team_2","right":"team_1"},
             "score_path":[row(0,"0:0"),row(1,"0:1","right"),row(2,"1:1","left"),
                           row(3,"2:1","left"),row(4,"2:2","right"),row(5,"3:2","left")]}
        r=match(t,normalize(e),e,doc)["candidates"]
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["subjects"],["team_2"])
        self.assertEqual([n["score"] for n in r[0]["nodes"]],["0:1","1:1","2:1"])
        self.assertTrue(all(n["media_window"] is None for n in r[0]["nodes"]))
        self.assertFalse(r[0]["release_authorized"])
        doc["score_path"]=doc["score_path"][:-1]
        self.assertEqual(match(t,normalize(e),e,doc)["candidates"],[])
        doc["video_id"]="other"
        with self.assertRaises(ValueError):
            match(t,normalize(e),e,doc)

    def test_score_observation_is_not_goal_action(self):
        a=atom("x",10,"","Pass")
        a["scores"]={"score_recognition":"2:1"}
        r=normalize(evidence(a))["atoms"][0]
        self.assertEqual(r["score_observation"],[2,1])
        self.assertNotIn("goal_action",r["predicates"])


    def test_real_note_coordinated_shot(self):
        e=evidence(atom("x",10,"2队球员看到进攻机会，选择打门","Shot"))
        self.assertEqual(normalize(e)["atoms"][0]["predicates"]["attacking_threat"]["actor"],"team_2")

if __name__=="__main__":
    unittest.main()
