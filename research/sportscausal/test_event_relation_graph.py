import unittest
from copy import deepcopy
from test_v3r_general import atom, evidence, template
from test_causal_episodes import chain
from episode_semantics import normalize_for_episodes
from event_relation_graph import build_relation_graph
from episode_goal_binding import bind_goals
from r2a3_patterns import project_graph
from episode_patterns import match_episodes


def graph(e,score=None,use_chains=True):
    return build_relation_graph(normalize_for_episodes(e),e,score,use_chains=use_chains)


def projection(g,p):
    return [x for x in project_graph(g)["episodes"] if x["predicate"]==p]


def score_doc(t=100,side="left"):
    return {"video_id":"v","score_side_mapping":{"left":"team_2","right":"team_1"},
            "score_path":[{"opening":True,"score":"0:0","t_sec":0},
                          {"opening":False,"score":"1:0" if side=="left" else "0:1",
                           "t_sec":t,"delta_side":side,"carrier_event_id":"carrier"}]}


class RelationGraphTests(unittest.TestCase):
    def test_delivery_dual_view_even_without_chain(self):
        e=evidence(atom("d",10,"1队球员发角球","Corner_kick"),atom("s",12,"2队守门员扑救"))
        chain(e,["d","s"],subtype="outcome_other")
        for mode in (True,False):
            g=graph(e,use_chains=mode)
            self.assertEqual(len(g["edges"]),1)
            attack=projection(g,"attacking_threat")
            rescue=projection(g,"goalkeeper_rescue")
            self.assertEqual((attack[0]["actor"],rescue[0]["actor"]),("team_1","team_2"))
            self.assertEqual(attack[0]["event_ids"],["d","s"])
            self.assertEqual(attack[0]["component_id"],rescue[0]["component_id"])
    def test_ordinary_catch_not_threat(self):
        e=evidence(atom("d",10,"1队球员发角球","Corner_kick"),atom("s",12,"2队守门员将球抱住"))
        self.assertFalse(projection(graph(e),"attacking_threat"))
        self.assertFalse(projection(graph(e),"goalkeeper_rescue"))
    def test_shot_interception_from_other_subtype(self):
        e=evidence(atom("s",10,"1队球员带球射门","Shot",{"Shot_Result":["Shot_On_Target"]}),
                   atom("k",11,"2队守门员关键拦截","Defensive_action",{"Defender":["2队守门员"],"Attacker":["1队球员"]}))
        chain(e,["s","k"],subtype="outcome_other")
        g=graph(e)
        self.assertEqual(g["edges"][0]["chain_support"][0]["subtype"],"outcome_other")
        self.assertEqual(len(projection(g,"attacking_threat")),1)
        self.assertEqual(projection(g,"goalkeeper_rescue")[0]["event_ids"],["s","k"])
    def test_deflection_then_followup_single_path(self):
        e=evidence(atom("d",10,"1队球员发角球","Corner_kick"),
                   atom("k",12,"2队守门员用手将球打出","Defensive_action",{"Defender":["2队守门员"]}),
                   atom("s",14,"1队球员接球后打门","Shot",{"Shot_Result":["Shot_Wide"]}))
        chain(e,["d","k","s"],subtype="second_phase_after_frame_chain")
        g=graph(e)
        self.assertEqual([x["kind"] for x in g["edges"]],["delivery_keeper","keeper_deflection_followup"])
        eps=projection(g,"attacking_threat")
        self.assertEqual(len(eps),1)
        self.assertEqual(eps[0]["event_ids"],["d","k","s"])
        self.assertEqual(projection(g,"goalkeeper_rescue")[0]["event_ids"],["d","k","s"])
    def test_explicit_recovery_reference_without_chain(self):
        e=evidence(atom("k",10,"2队13号守门员在小禁区内将球顶出"),
                   atom("r",11,"1队球员在禁区将2队守门员扑出的球控下","Ball_possession"))
        g=graph(e,use_chains=False)
        self.assertEqual(g["edges"][0]["kind"],"keeper_deflection_followup")
        self.assertEqual(projection(g,"attacking_threat")[0]["actor"],"team_1")
        self.assertEqual(projection(g,"goalkeeper_rescue")[0]["actor"],"team_2")
    def test_both_unknown_with_turnover_context_not_forced(self):
        e=evidence(atom("p",10,"1队16号向前直塞给1队14号","Pass"),
                   atom("d",11,"","Defensive_action"),atom("s",12,"","Shot"),
                   atom("k",13,""),atom("r",16,"2队20号球员在禁区传球","Pass"))
        chain(e,["p","d","s","k","r"],state="PARTIAL")
        g=graph(e)
        self.assertFalse(g["inferred_roles"])
        u=g["unresolved_relations"][0]
        self.assertEqual(len(u["actor_hypotheses"]),2)
        self.assertTrue(u["context_clues"][0]["possible_turnover"])
        self.assertFalse(u["resolved"])
    def test_three_event_explicit_reference_resolves_roles(self):
        e=evidence(atom("s",10,"","Shot"),atom("k",11,""),
                   atom("r",12,"1队球员在禁区将2队守门员扑出的球控下","Ball_possession"))
        chain(e,["s","k","r"])
        g=graph(e)
        self.assertEqual({(x["event_id"],x["actor"]) for x in g["inferred_roles"]},{("s","team_1"),("k","team_2")})
        self.assertEqual(len(projection(g,"attacking_threat")),1)
        self.assertFalse(graph(e,use_chains=False)["inferred_roles"])
    def test_partial_missing_member_does_not_create_role_link(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"),atom("k",11,""))
        chain(e,["s","missing","k"],state="PARTIAL",available=["s","k"])
        self.assertFalse(graph(e)["inferred_roles"])
    def test_conflicting_opponent_not_propagated(self):
        e=evidence(atom("p",10,"2队球员传中","Pass"),atom("k",11,"面对1队球员的传中球，2队守门员给扑飞"))
        chain(e,["p","k"])
        g=graph(e)
        self.assertFalse(g["edges"])
        self.assertEqual(g["rejected_edges"][0]["reason"],"actor_conflict")
    def test_score_goal_and_shot_role_inference(self):
        e=evidence(atom("s",9,"","Shot"),atom("g",10,"","Goal"),atom("carrier",100,"","Pass"))
        chain(e,["s","g"],subtype="team_buildup_goal")
        g=graph(e,score_doc())
        self.assertEqual(g["goal_bindings"]["bindings"][0]["actor"],"team_2")
        self.assertEqual(g["goal_bindings"]["bindings"][0]["media_window"],[9,11])
        self.assertEqual(g["inferred_roles"][0]["actor"],"team_2")
        ep=projection(g,"attacking_threat")[0]
        self.assertEqual(ep["event_ids"],["s","g"])
        self.assertNotIn("carrier",ep["event_ids"])
        no=graph(e,score_doc(),use_chains=False)
        self.assertEqual(projection(no,"attacking_threat")[0]["event_ids"],["g"])
        self.assertFalse(graph(e)["inferred_roles"])
    def test_score_goal_ambiguity_no_nearest_guess(self):
        e=evidence(atom("g1",10,"","Goal"),atom("g2",20,"","Goal"))
        b=bind_goals(normalize_for_episodes(e),score_doc())
        self.assertFalse(b["bindings"])
        self.assertEqual(len(b["unresolved"][0]["candidate_ids"]),2)
    def test_score_source_and_role_conflict(self):
        e=evidence(atom("g",10,"1队9号头球破门","Goal"))
        b=bind_goals(normalize_for_episodes(e),score_doc())
        self.assertFalse(b["bindings"])
        self.assertEqual(b["unresolved"][0]["conflicting_goal_ids"],["g"])
        doc=score_doc(); doc["video_id"]="wrong"
        with self.assertRaises(ValueError): graph(e,doc)
    def test_saved_semantics_mismatch_rejected(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"))
        s=normalize_for_episodes(e)
        e["atoms"]["s"]["t"]=11
        with self.assertRaises(ValueError): build_relation_graph(s,e)
    def test_goal_shot_conflict_does_not_override_actor(self):
        e=evidence(atom("s",9,"1队球员射门","Shot"),atom("g",10,"","Goal"))
        chain(e,["s","g"],subtype="team_buildup_goal")
        g=graph(e,score_doc())
        self.assertFalse(g["edges"])
        self.assertEqual(g["rejected_edges"][0]["reason"],"shot_goal_conflict")
        self.assertEqual(projection(g,"attacking_threat")[0]["actor"],"team_2")

if __name__=="__main__":
    unittest.main()
