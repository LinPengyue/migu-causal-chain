import unittest
from copy import deepcopy
from test_v3r_general import atom, evidence, template
from test_causal_episodes import chain
from episode_semantics import normalize_for_episodes
from event_relation_graph import build_relation_graph
from r2a4_relation_graph import build_role_graph
from r2a4_patterns import project_roles, match_mixed_alternation
from episode_patterns import match_episodes
from test_event_relation_graph import score_doc

def graph(e,score=None,**kwargs):
    return build_role_graph(normalize_for_episodes(e),e,score,**kwargs)

def eps(g,p):
    return [x for x in project_roles(g)["episodes"] if x["predicate"]==p]

class R2a4RoleTests(unittest.TestCase):
    def test_empty_goal_does_not_assign_shooter_or_executor(self):
        e=evidence(atom("s",9,"","Shot"),atom("g",10,"","Goal"),atom("carrier",100,"","Pass"))
        chain(e,["s","g"],subtype="team_buildup_goal")
        g=graph(e,score_doc())
        r=g["goal_role_claims"][0]
        self.assertEqual(r["score_beneficiary"],"team_2")
        self.assertIsNone(r["goal_executor"])
        self.assertIsNone(r["attacking_team"])
        self.assertFalse(g["inferred_roles"])
        self.assertFalse(g["edges"])
        self.assertEqual(g["outcome_context_edges"][0]["kind"],"shot_goal_context")
        self.assertEqual(eps(g,"scoring_outcome")[0]["event_ids"],["s","g"])
        self.assertEqual(eps(g,"scoring_outcome")[0]["core_event_ids"],["g"])
        self.assertEqual(eps(g,"scoring_outcome")[0]["anchor_t"],10)
        self.assertNotIn("carrier",eps(g,"scoring_outcome")[0]["event_ids"])
        self.assertFalse(eps(g,"attacking_threat"))
        self.assertFalse(eps(g,"attacking_attempt"))
        self.assertEqual(g["observation_tasks"][0]["task_type"],"goal_execution_roles")
    def test_explicit_own_goal_keeps_opposite_executor_and_beneficiary(self):
        e=evidence(atom("g",10,"1队9号自摆乌龙","Goal"))
        g=graph(e,score_doc())
        r=g["goal_role_claims"][0]
        self.assertEqual(r["goal_executor"],"team_1")
        self.assertEqual(r["score_beneficiary"],"team_2")
        self.assertEqual(r["goal_kind"],"own_goal_explicit")
        self.assertIsNone(r["attacking_team"])
        self.assertFalse(r["role_conflict"])
        self.assertEqual(len(eps(g,"scoring_outcome")),1)
        self.assertFalse(eps(g,"attacking_threat"))
    def test_own_goal_shot_preserves_independent_other_side(self):
        e=evidence(atom("s",9,"1队球员射门","Shot"),
                   atom("g",10,"","Goal"))
        chain(e,["s","g"])
        g=graph(e,score_doc())
        self.assertEqual(g["outcome_context_edges"][0]["shooter"],"team_1")
        self.assertEqual(g["outcome_context_edges"][0]["score_beneficiary"],"team_2")
        self.assertEqual(eps(g,"attacking_attempt")[0]["actor"],"team_1")
        self.assertFalse(g["inferred_roles"])
    def test_ordinary_goal_preserves_explicit_independent_role(self):
        e=evidence(atom("g",10,"2队9号头球破门","Goal"))
        for score in (None,score_doc()):
            g=graph(e,score)
            self.assertEqual(g["goal_role_claims"][0]["goal_executor"],"team_2")
            self.assertEqual(eps(g,"attacking_threat")[0]["actor"],"team_2")
            self.assertEqual(len(eps(g,"scoring_outcome")),int(score is not None))
    def test_even_explicit_goal_does_not_assign_empty_shot(self):
        e=evidence(atom("s",9,"","Shot"),atom("g",10,"2队9号头球破门","Goal"))
        chain(e,["s","g"])
        g=graph(e,score_doc())
        self.assertFalse(g["inferred_roles"])
        self.assertFalse(eps(g,"attacking_attempt"))
        self.assertEqual(len(eps(g,"attacking_threat")),1)
        self.assertIsNone(g["outcome_context_edges"][0]["shooter"])
    def test_execution_disagreement_not_localization_conflict(self):
        e=evidence(atom("g",10,"1队9号头球破门","Goal"))
        g=graph(e,score_doc())
        r=g["goal_role_claims"][0]
        self.assertEqual(r["score_beneficiary"],"team_2")
        self.assertEqual(r["goal_executor"],"team_1")
        self.assertTrue(r["role_conflict"])
        self.assertFalse(eps(g,"attacking_threat"))
        self.assertEqual(len(eps(g,"scoring_outcome")),1)
    def test_note_attribute_conflict_retained(self):
        e=evidence(atom("g",10,"1队9号头球破门","Goal",{"BallController_team":["team_2"]}))
        g=graph(e,score_doc())
        r=g["goal_role_claims"][0]
        self.assertEqual(r["execution_status"],"CONFLICT")
        self.assertTrue(r["role_conflict"])
        self.assertIsNone(r["goal_executor"])
        self.assertEqual(r["score_beneficiary"],"team_2")
    def test_attribute_only_is_not_execution(self):
        e=evidence(atom("g",10,"","Goal",{"BallController_team":["team_2"]}))
        g=graph(e,score_doc())
        self.assertIsNone(g["goal_role_claims"][0]["goal_executor"])
        self.assertFalse(eps(g,"attacking_threat"))
    def test_cancelled_and_replay_goals_not_localized(self):
        e=evidence(atom("g",10,"1队球员进球无效","Goal"),
                   atom("r",11,"","Goal",phase="REPLAY"))
        g=graph(e,score_doc())
        self.assertFalse(g["goal_bindings"]["bindings"])
        self.assertFalse(eps(g,"scoring_outcome"))
        t=next(x for x in g["observation_tasks"] if x["task_type"]=="missing_goal_localization")
        self.assertFalse(t["media_windows"])
        self.assertEqual(t["confirmation_t_sec"],100)
    def test_ambiguous_goal_localization_is_observation_task(self):
        e=evidence(atom("a",10,"","Goal"),atom("b",20,"","Goal"))
        g=graph(e,score_doc())
        self.assertFalse(g["goal_bindings"]["bindings"])
        task=next(x for x in g["observation_tasks"] if x["task_type"]=="missing_goal_localization")
        self.assertEqual(set(task["event_ids"]),{"a","b"})
        self.assertFalse(task["media_windows"])
    def test_no_chain_retains_goal_but_not_shot_context(self):
        e=evidence(atom("s",9,"","Shot"),atom("g",10,"","Goal"))
        chain(e,["s","g"])
        g=graph(e,score_doc(),use_chains=False)
        self.assertFalse(g["outcome_context_edges"])
        self.assertEqual(eps(g,"scoring_outcome")[0]["event_ids"],["g"])
    def test_partial_missing_middle_not_context(self):
        e=evidence(atom("s",9,"","Shot"),atom("g",10,"","Goal"))
        chain(e,["s","missing","g"],state="PARTIAL",available=["s","g"])
        g=graph(e,score_doc())
        self.assertFalse(g["outcome_context_edges"])
    def test_unresolved_save_has_observation_task(self):
        e=evidence(atom("s",10,"","Shot"),atom("k",11,""))
        chain(e,["s","k"])
        g=graph(e)
        self.assertFalse(g["inferred_roles"])
        t=g["observation_tasks"][0]
        self.assertEqual(t["task_type"],"shot_save_roles")
        self.assertEqual(len(t["actor_hypotheses"]),2)
        self.assertTrue(t["preview_only"])
    def test_cache_equivalent_to_new_safe_base(self):
        e=evidence(atom("d",10,"1队球员发角球","Corner_kick"),atom("k",12,"2队守门员扑救"),
                   atom("s",49,"","Shot"),atom("g",50,"","Goal"))
        chain(e,["s","g"])
        s=normalize_for_episodes(e)
        base=build_relation_graph(s,e,None)
        cached=build_role_graph(s,e,score_doc(),base_graph=base)
        fresh=build_role_graph(s,e,score_doc())
        self.assertTrue(cached["reused_without_score_graph"])
        self.assertEqual(cached["edges"],fresh["edges"])
        self.assertEqual(cached["goal_role_claims"],fresh["goal_role_claims"])
        self.assertEqual(cached["outcome_context_edges"],fresh["outcome_context_edges"])
        self.assertEqual(project_roles(cached)["episodes"],project_roles(fresh)["episodes"])
    def test_reject_score_contaminated_cache(self):
        e=evidence(atom("s",9,"","Shot"),atom("g",10,"","Goal"))
        chain(e,["s","g"])
        s=normalize_for_episodes(e)
        bad=build_relation_graph(s,e,score_doc())
        with self.assertRaises(ValueError):
            build_role_graph(s,e,score_doc(),base_graph=bad)
    def test_reject_cache_from_different_source(self):
        e=evidence(atom("s",10,"1队球员射门","Shot"))
        s=normalize_for_episodes(e)
        bad=build_relation_graph(s,e,None)
        bad["atoms"][0]["t"]+=1
        with self.assertRaises(ValueError):
            build_role_graph(s,e,None,base_graph=bad)
    def test_mixed_roles_not_strict_attack_runs(self):
        e=evidence(atom("a",10,"1队球员射门","Shot",{"Shot_Result":["Shot_On_Target"]}),
                   atom("g",300,"","Goal"),
                   atom("b",600,"1队球员射门","Shot",{"Shot_Result":["Shot_On_Target"]}))
        g=graph(e,score_doc(t=310))
        bundle=project_roles(g)
        t=template("alternate","attacking_threat",3)
        self.assertFalse(match_episodes(t,bundle)["candidates"])
        result=match_mixed_alternation(t,bundle)
        c=result["candidates"][0]
        self.assertEqual([n["actor_role"] for n in c["nodes"]],
                         ["attacking_team","score_beneficiary","attacking_team"])
        self.assertEqual(c["nodes"][1]["predicate"],"scoring_outcome")
        self.assertEqual(c["n_attack_evidence_nodes"],2)
        self.assertEqual(c["n_score_only_nodes"],1)
        self.assertFalse(result["strict_threat_metric_eligible"])
    def test_mixed_does_not_duplicate_goal_with_explicit_attack(self):
        e=evidence(atom("g",300,"2队9号头球破门","Goal"))
        g=graph(e,score_doc(t=310))
        bundle=project_roles(g)
        result=match_mixed_alternation(template("alternate","attacking_threat",3),bundle)
        self.assertEqual(result["n_mixed_episodes"],1)
    def test_score_only_alternation_not_mixed_attack_story(self):
        e=evidence(atom("a",100,"","Goal"),atom("b",400,"","Goal"),atom("c",700,"","Goal"))
        s=score_doc(t=110)
        s["score_path"] += [{"opening":False,"score":"1:1","t_sec":410,"delta_side":"right"},
                            {"opening":False,"score":"2:1","t_sec":710,"delta_side":"left"}]
        g=graph(e,s)
        result=match_mixed_alternation(template("alternate","attacking_threat",3),project_roles(g))
        self.assertFalse(result["candidates"])
        self.assertEqual(result["score_only_sequence_count"],1)

if __name__=="__main__":
    unittest.main()
