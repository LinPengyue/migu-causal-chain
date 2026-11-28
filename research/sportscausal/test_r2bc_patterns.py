import unittest
from copy import deepcopy
from test_v3r_general import atom, evidence
from test_causal_episodes import chain
from test_r2a4_roles import graph
from r2a4_patterns import project_roles
from r2bc_patterns import default_templates, run
from state_story_patterns import state_candidates
from relation_story_patterns import relation_candidates
from phase_story_patterns import phase_candidates

def t(name):
    return next(x for x in default_templates() if x["template_id"]==name)

def score(*steps):
    path=[{"opening":True,"score":"0:0","t_sec":0,"delta_side":None}]
    old=(0,0)
    for time,s in steps:
        a,b=map(int,s.split(":"))
        path.append({"opening":False,"score":s,"t_sec":time,
                     "delta_side":"left" if a>old[0] else "right",
                     "carrier_event_id":"score_carrier_"+str(time)})
        old=a,b
    return {"video_id":"v","score_side_mapping":{"left":"team_1","right":"team_2"},
            "score_path":path}

def shot(i,time,side):
    return atom(i,time,f"{side}队球员射门","Shot",{"Shot_Result":["Shot_On_Target"]})

class StateTests(unittest.TestCase):
    def test_comeback_material_and_state_actor_distinct(self):
        e=evidence(atom("g1",100,"","Goal"),atom("g2",400,"","Goal"),atom("g3",700,"","Goal"),
                   shot("a",200,1))
        s=score((110,"0:1"),(410,"1:1"),(710,"2:1"))
        b=project_roles(graph(e,s))
        c=state_candidates(t("comeback"),s,b)[0]
        self.assertEqual(c["subjects"],["team_1"])
        self.assertEqual([n["event_ids"] for n in c["nodes"]],[["g1"],["g2"],["g3"]])
        self.assertEqual(c["nodes"][0]["actor"],"team_1")
        self.assertEqual(c["nodes"][0]["score_beneficiary"],"team_2")
        self.assertEqual(c["nodes"][0]["anchor_t"],100)
        self.assertEqual(c["interval_context"][0]["context_candidates"][0]["event_ids"],["a"])
        self.assertFalse(c["first_live_verified"])
    def test_missing_action_is_task_not_media(self):
        e=evidence(atom("g1",100,"","Goal"),atom("g3",700,"","Goal"))
        s=score((110,"0:1"),(410,"1:1"),(710,"2:1"))
        c=state_candidates(t("comeback"),s,project_roles(graph(e,s)))[0]
        n=c["nodes"][1]
        self.assertEqual(n["localization_status"],"missing_action")
        self.assertEqual(n["event_ids"],[])
        self.assertEqual(n["media_windows"],[])
        self.assertTrue(n["observation_task_ids"])
        self.assertEqual(c["unlocalized_state_indices"],[2])
    def test_opening_state_is_not_clip_and_all_run_steps_retained(self):
        e=evidence(atom("g1",100,"","Goal"),atom("g2",400,"","Goal"))
        s=score((110,"1:0"),(410,"2:0"))
        c=state_candidates(t("lead_preservation"),s,project_roles(graph(e,s)))[0]
        self.assertEqual([n["score"] for n in c["nodes"]],["0:0","1:0","2:0"])
        self.assertFalse(c["nodes"][0]["story_anchor"])
        self.assertFalse(c["nodes"][0]["media_windows"])
    def test_score_binding_path_mismatch_rejected(self):
        e=evidence(atom("g",100,"","Goal"))
        s=score((110,"1:0"))
        b=project_roles(graph(e,s))
        s["score_path"][1]["t_sec"]=111
        with self.assertRaises(ValueError):
            state_candidates(t("lead_preservation"),s,b)

class PathTests(unittest.TestCase):
    def fixture(self,*extra):
        e=evidence(atom("r",80,"2队球员发角球","Corner_kick"),
                   atom("p",85,"2队球员传球","Pass"),atom("s",90,"","Shot"),
                   atom("g",92,"","Goal"),*extra)
        return e,score((100,"0:1"))
    def test_partial_contiguous_subpath_with_intermediate_evidence(self):
        e,s=self.fixture()
        chain(e,["missing","r","p","s","g"],state="PARTIAL",available=["r","p","s","g"],subtype="outcome_other")
        c=relation_candidates(t("set_piece_breakthrough"),graph(e,s),e)[0]
        self.assertEqual(c["path_alternatives"][0]["event_ids"],["r","p","s","g"])
        self.assertEqual(c["path_alternatives"][0]["intermediate_event_ids"],["p","s"])
        self.assertEqual(c["nodes"][1]["actor_role"],"score_beneficiary")
        self.assertIsNone(c["nodes"][1]["goal_roles"][0]["goal_executor"])
        self.assertFalse(c["edges"][0]["causal_verified"])
    def test_missing_middle_member_blocks_path(self):
        e,s=self.fixture()
        chain(e,["r","p","missing","s","g"],state="PARTIAL",available=["r","p","s","g"])
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))
    def test_intervening_opponent_restart_blocks_even_when_not_chain_member(self):
        e,s=self.fixture(atom("x",87,"1队球员发任意球","Free_kick"))
        chain(e,["r","p","s","g"])
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))
    def test_intervening_opponent_possession_blocks_path(self):
        e,s=self.fixture(atom("x",87,"1队球员控球","Ball_possession"))
        chain(e,["r","p","s","g"])
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))
    def test_does_not_stitch_distinct_chains(self):
        e,s=self.fixture()
        chain(e,["r","p"])
        first=deepcopy(e["chains"])
        chain(e,["p","s","g"])
        # Fixture helper may use the same default key; assign independent IDs.
        second=next(iter(e["chains"].values()))
        a=next(iter(first.values()))
        a["chain_id"]="left"; second["chain_id"]="right"
        e["chains"]={"left":a,"right":second}
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))
    def test_turnover_to_score_path(self):
        e=evidence(atom("r",80,"2队球员抢断","Defensive_action"),
                   atom("p",85,"2队球员传球","Pass"),atom("g",92,"","Goal"))
        s=score((100,"0:1"))
        chain(e,["r","p","g"],subtype="outcome_other")
        c=relation_candidates(t("turnover_to_goal"),graph(e,s),e)[0]
        self.assertEqual(c["nodes"][0]["actor_role"],"ball_recovery_team")
    def test_opposite_beneficiary_not_same_side_path(self):
        e,_=self.fixture()
        chain(e,["r","p","s","g"])
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,score((100,"1:0"))),e))
    def test_path_bounds_are_explicit_config(self):
        e,s=self.fixture()
        chain(e,["r","p","s","g"])
        spec=t("set_piece_breakthrough")
        spec["pattern"]["max_span_sec"]=8
        spec["pattern"]["max_edge_gap_sec"]=8
        self.assertFalse(relation_candidates(spec,graph(e,s),e))


    def unlabelled_corner(self, *, note="", attrs=None, phase="LIVE", subtype="corner_coop_goal"):
        restart=atom("r",80,note,"Corner_kick",attrs,phase=phase)
        restart["enrichment_provenance"]="causal_atom_fill"
        e=evidence(restart,atom("s",82,"","Shot"),atom("g",84,"","Goal"))
        e["input_tier"]="HUMAN_ATOM_ENRICHED_DEV"
        chain(e,["missing","r","s","g"],state="PARTIAL",available=["r","s","g"],subtype=subtype)
        return e,score((100,"0:1"))

    def test_unlabelled_corner_is_hypothesis_not_execution_predicate(self):
        e,s=self.unlabelled_corner()
        g=graph(e,s); b=project_roles(g); before=deepcopy((e,g,b))
        result=run(e,g,b,s,[t("set_piece_breakthrough")])
        c=result["results"]["set_piece_breakthrough"]["candidates"][0]
        h=c["restart_actor_hypothesis"]
        self.assertEqual(h["actor_hypothesis"],"team_2")
        self.assertEqual(h["status"],"CONDITIONAL_UNVERIFIED")
        self.assertEqual(h["support_chain_ids"],["p"])
        self.assertFalse(h["execution_verified"])
        self.assertEqual(c["nodes"][0]["actor_role"],"restart_executor_hypothesis")
        self.assertEqual(c["path_alternatives"][0]["event_ids"],["r","s","g"])
        task=next(x for x in result["observation_tasks"] if x["task_type"]=="relation_path_verification")
        self.assertEqual(task["restart_actor_hypothesis"],h)
        self.assertFalse(task["resolved"])
        self.assertNotIn("set_piece_execution",next(x for x in g["atoms"] if x["event_id"]=="r")["predicates"])
        self.assertEqual((e,g,b),before)
        self.assertFalse(c["release_authorized"])

    def test_unlabelled_corner_rejects_untyped_support_and_missing_middle(self):
        e,s=self.unlabelled_corner(subtype="outcome_other")
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))
        e,s=self.unlabelled_corner()
        chain(e,["r","missing","s","g"],state="PARTIAL",available=["r","s","g"],subtype="corner_coop_goal")
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))

    def test_unlabelled_corner_no_override_or_nonlive(self):
        for kwargs in ({"note":"1队球员发角球","attrs":{"BallController_team":["team_2"]}},
                       {"phase":"REPLAY"},{"note":"1队球员发角球"}):
            e,s=self.unlabelled_corner(**kwargs)
            self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))

    def test_unlabelled_corner_rejects_opponent_possession_and_shot(self):
        for extra in (atom("x",81,"1队球员控球","Ball_possession"),
                      atom("x",81,"1队球员射门","Shot")):
            e,s=self.unlabelled_corner()
            e["atoms"]["x"]=extra
            self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))

    def test_unlabelled_corner_needs_bound_non_own_goal_and_shot(self):
        e,s=self.unlabelled_corner()
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e),e))
        e["atoms"]["g"]["notes"]="1队球员自摆乌龙"
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))
        e,s=self.unlabelled_corner()
        e["atoms"].pop("s")
        chain(e,["r","g"],subtype="corner_coop_goal")
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))

    def test_unlabelled_corner_not_general_score_propagation(self):
        e,s=self.unlabelled_corner()
        e["atoms"]["r"].pop("enrichment_provenance")
        self.assertFalse(relation_candidates(t("set_piece_breakthrough"),graph(e,s),e))

class PhaseTests(unittest.TestCase):
    def test_two_independent_threats_each_side(self):
        e=evidence(shot("a",10,1),shot("b",20,1),shot("c",40,2),shot("d",50,2))
        b=project_roles(graph(e))
        r=phase_candidates(t("threat_phase_change"),b)
        c=r["candidates"][0]
        self.assertEqual(c["subjects"],["team_1","team_2"])
        self.assertEqual(c["switch_search_interval"],[21,39])
        self.assertEqual([p["n_observed_episodes"] for p in c["phases"]],[2,2])
        self.assertFalse(c["quality_verified"])
    def test_one_threat_does_not_define_sustained_phase(self):
        e=evidence(shot("a",10,1),shot("b",20,1),shot("c",40,2))
        self.assertFalse(phase_candidates(t("threat_phase_change"),project_roles(graph(e)))["candidates"])
    def test_score_only_nodes_not_attack_phase(self):
        e=evidence(shot("a",10,1),shot("b",20,1),atom("g1",400,"","Goal"),atom("g2",700,"","Goal"))
        s=score((410,"0:1"),(710,"0:2"))
        self.assertFalse(phase_candidates(t("threat_phase_change"),project_roles(graph(e,s)))["candidates"])
    def test_overlapping_opposite_actions_split_ambiguous_run(self):
        e=evidence(shot("a",10,1),shot("b",20,1),shot("x",20.5,2),shot("c",40,2),shot("d",50,2))
        r=phase_candidates(t("threat_phase_change"),project_roles(graph(e)))
        self.assertTrue(r["ambiguous_episode_ids"])
        self.assertFalse(r["candidates"])

class IntegrationTests(unittest.TestCase):
    def test_combined_pack_reads_frozen_graph(self):
        e=evidence(atom("g1",100,"","Goal"),atom("g2",400,"","Goal"),atom("g3",700,"","Goal"))
        s=score((110,"0:1"),(410,"1:1"),(710,"2:1"))
        g=graph(e,s); b=project_roles(g)
        before=deepcopy((g,b))
        result=run(e,g,b,s,default_templates())
        self.assertEqual(len(result["results"]),6)
        self.assertEqual(len(result["results"]["comeback"]["candidates"]),1)
        self.assertEqual(result["observation_tasks"],g["observation_tasks"])
        self.assertEqual((g,b),before)
        self.assertFalse(result["release_authorized"])
    def test_mismatched_bundle_rejected(self):
        e=evidence(shot("a",10,1))
        s=score()
        g=graph(e,s); b=project_roles(g)
        b["observation_tasks"]=[{"task_id":"invented"}]
        with self.assertRaises(ValueError):
            run(e,g,b,s,default_templates())

    def test_relation_observation_task_keeps_path_alternatives(self):
        e=evidence(atom("r",80,"2队球员发角球","Corner_kick"),
                   atom("p",85,"2队球员传球","Pass"),atom("g",92,"","Goal"))
        s=score((100,"0:1"))
        chain(e,["r","p","g"])
        g=graph(e,s); b=project_roles(g)
        result=run(e,g,b,s,[t("set_piece_breakthrough")])
        c=result["results"]["set_piece_breakthrough"]["candidates"][0]
        task=next(x for x in result["observation_tasks"] if x["task_type"]=="relation_path_verification")
        self.assertIn(task["task_id"],c["observation_task_ids"])
        self.assertEqual(task["path_alternatives"],c["path_alternatives"])
        self.assertFalse(task["resolved"])

    def test_phase_observation_task_uses_search_interval_not_clip(self):
        e=evidence(shot("a",10,1),shot("b",20,1),shot("c",40,2),shot("d",50,2))
        s=score(); g=graph(e,s); b=project_roles(g)
        result=run(e,g,b,s,[t("threat_phase_change")])
        task=next(x for x in result["observation_tasks"] if x["task_type"]=="phase_switch_verification")
        self.assertEqual(task["search_interval"],[21,39])
        self.assertFalse(task["media_windows"])
        self.assertTrue(task["preview_only"])


if __name__=="__main__":
    unittest.main()
