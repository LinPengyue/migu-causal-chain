import unittest
from test_v3r_general import atom,evidence,template
from episode_semantics import normalize_for_episodes
from causal_episodes import build_episodes
from episode_patterns import match_episodes,_diff

def chain(e,ids,state="FULL",available=None,subtype="shot_save_chain",cid="p"):
    e["chains"][cid]={"chain_id":cid,"state":state,"subtype":subtype,
                      "event_ids":ids,"available_event_ids":ids if available is None else available}

def pair(e,use_chains=True):
    return build_episodes(normalize_for_episodes(e),e,use_chains=use_chains)

class EpisodeTests(unittest.TestCase):
    def test_cross_clause_actor_and_passive(self):
        e=evidence(atom("a",10,"2队球员看到进攻机会，选择打门","Shot"),
                   atom("b",20,"1队球员在禁区，起脚射门，球经过折射飞出底线","Shot"),
                   atom("c",30,"1队球员被对手射门","Shot"),
                   atom("d",40,"1队球员被抢断，起脚射门","Shot"),
                   atom("e",50,"1队球员射门被2队球员阻挡","Shot"))
        rows=normalize_for_episodes(e)["atoms"]
        self.assertEqual([x["predicates"].get("attacking_attempt",{}).get("actor") for x in rows],
                         ["team_2","team_1",None,None,"team_1"])
    def test_action_is_not_automatically_rescue(self):
        e=evidence(atom("catch",10,"2队13号守门员在禁区将球抱住"),
                   atom("clear",20,"2队13号守门员在禁区将球解围踢走","Defensive_action",
                        {"Attacker":["1队球员"],"Defender":["team_2_player_13"]}),
                   atom("save",30,"2队守门员扑住了1队队员的打门"),
                   atom("wide",40,"1队球员射门打偏","Shot",{"Shot_Result":["Shot_Wide"]}),
                   atom("target",50,"1队球员射门","Shot",{"Shot_Result":["Shot_On_Target"]}))
        rows=normalize_for_episodes(e)["atoms"]
        for row in rows[:2]:
            self.assertIn("goalkeeper_action",row["predicates"])
            self.assertNotIn("goalkeeper_rescue",row["predicates"])
        self.assertEqual(rows[2]["predicates"]["attacking_threat"]["actor"],"team_1")
        self.assertIn("attacking_attempt",rows[3]["predicates"])
        self.assertNotIn("attacking_threat",rows[3]["predicates"])
        self.assertIn("attacking_threat",rows[4]["predicates"])
    def test_chain_changes_roles_and_candidate_not_just_metadata(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"),
                   atom("k",12,""),atom("k2",40,"2队守门员扑救"))
        chain(e,["s","k"])
        full,base=pair(e),pair(e,False)
        self.assertEqual(full["inferred_roles"][0]["event_id"],"k")
        self.assertEqual(full["inferred_roles"][0]["actor"],"team_2")
        self.assertEqual(len(match_episodes(template(),full)["candidates"]),1)
        self.assertEqual(match_episodes(template(),base)["candidates"],[])
        self.assertTrue(_diff(full,base)["with_chain_only"])
        ep=next(x for x in full["episodes"] if x["predicate"]=="goalkeeper_rescue" and "k" in x["event_ids"])
        self.assertEqual(ep["event_ids"],["s","k"])
        self.assertEqual(ep["core_event_ids"],["k"])
        self.assertFalse(ep["causal_verified"])
        self.assertEqual(e["atoms"]["k"]["notes"],"")
    def test_both_unknown_remain_unbound(self):
        e=evidence(atom("s",10,"","Shot"),atom("k",12,""))
        chain(e,["s","k"])
        r=pair(e)
        self.assertFalse(r["inferred_roles"])
        self.assertFalse(r["local_links"])
        self.assertIn("both_roles_missing",[x["reason"] for x in r["rejected_links"]])
    def test_partial_local_pair_not_missing_middle(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"),atom("k",12,""))
        chain(e,["missing","s","k"],"PARTIAL",["s","k"])
        r=pair(e)
        self.assertEqual(len(r["local_links"]),1)
        self.assertEqual(r["local_links"][0]["chain_support"][0]["state"],"PARTIAL")
        chain(e,["s","missing","k"],"PARTIAL",["s","k"])
        self.assertFalse(pair(e)["local_links"])
        del e["chains"]["p"]["event_ids"]
        self.assertFalse(pair(e)["local_links"])
    def test_no_cross_possession_or_same_team_propagation(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"),
                   atom("restart",11,"2队球员发角球","Corner_kick"),atom("k",12,""))
        chain(e,["s","k"])
        self.assertFalse(pair(e)["local_links"])
        e=evidence(atom("s",10,"2队球员射门","Shot"),atom("k",12,"2队守门员扑救"))
        chain(e,["s","k"])
        self.assertFalse(pair(e)["local_links"])
        e=evidence(atom("s",10,"1队球员射门","Shot"),atom("k",50,""))
        chain(e,["s","k"])
        self.assertFalse(pair(e)["local_links"])
    def test_wide_shot_and_nonlive_not_promoted(self):
        e=evidence(atom("s",10,"1队球员射门打偏","Shot",{"Shot_Result":["Shot_Wide"]}),
                   atom("k",12,"2队守门员扑救"))
        chain(e,["s","k"])
        self.assertFalse(pair(e)["local_links"])
        e=evidence(atom("s",10,"1队球员射门","Shot"),atom("k",12,"",phase="REPLAY"))
        chain(e,["s","k"])
        self.assertFalse(pair(e)["local_links"])
    def test_conflicting_actor_not_overwritten(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"),
                   atom("k",12,"2队守门员扑救","Save",{"Defender":["1队守门员"]}))
        chain(e,["s","k"])
        self.assertFalse(pair(e)["local_links"])
        self.assertFalse(pair(e)["inferred_roles"])
    def test_duplicate_chain_ids_do_not_duplicate_episode(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"),atom("k",12,"2队守门员扑救"))
        chain(e,["s","k"],cid="p1")
        chain(e,["s","k"],cid="p2")
        r=pair(e)
        self.assertEqual(len(r["local_links"]),1)
        self.assertEqual(len(r["local_links"][0]["chain_support"]),2)
        self.assertEqual(len([x for x in r["episodes"] if x["predicate"]=="goalkeeper_rescue"]),1)
    def test_delivery_catch_not_automatically_threat(self):
        e=evidence(atom("d",10,"1队球员发角球","Corner_kick"),
                   atom("k",12,"2队守门员将球抱住"))
        chain(e,["d","k"])
        r=pair(e)
        self.assertEqual(r["local_links"][0]["kind"],"delivery_keeper")
        self.assertFalse([x for x in r["episodes"] if x["predicate"]=="goalkeeper_rescue"])
    def test_alternate_on_danger_not_all_shots(self):
        e=evidence(atom("a",10,"1队球员射门","Shot",{"Shot_Result":["Shot_On_Target"]}),
                   atom("b",20,"2队球员射门","Shot",{"Shot_Result":["Shot_Wide"]}),
                   atom("c",30,"1队球员射门","Shot",{"Shot_Result":["Shot_On_Target"]}))
        t=template("alternate","attacking_threat",3)
        self.assertFalse(match_episodes(t,pair(e))["candidates"])
        e["atoms"]["b"]["attributes"]["Shot_Result"]=["Shot_On_Target"]
        self.assertEqual([r["actor"] for r in match_episodes(t,pair(e))["candidates"][0]["actor_runs"]],
                         ["team_1","team_2","team_1"])
    def test_media_window_union_does_not_fill_gaps(self):
        e=evidence(atom("s",10,"1队球员射门","Shot",window=[9,10]),
                   atom("k",13,"2队守门员扑救",window=[13,14]))
        chain(e,["s","k"])
        ep=next(x for x in pair(e)["episodes"] if x["predicate"]=="goalkeeper_rescue")
        self.assertEqual(ep["media_windows"],[[9,10],[13,14]])

if __name__=="__main__":
    unittest.main()
