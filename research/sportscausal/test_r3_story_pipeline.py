import unittest
import tempfile
from pathlib import Path
import json
import hashlib
from copy import deepcopy
from test_v3r_general import atom,evidence
from test_causal_episodes import chain
from test_r2a4_roles import graph
from r2a4_patterns import project_roles,match_mixed_alternation
from episode_patterns import match_episodes
from test_r2bc_patterns import score,shot
from r2bc_patterns import run,default_templates
from r3_story_pipeline import compile_pack,load_seed_manifest,write_pack
from story_graph_compiler import compile_story
from story_materializer import materialize
from template_graph import read

def fixture(*atoms):
    e=evidence(*atoms)
    e["duration_sec"]=1000
    return e

def pack(e,s,legacy=None):
    g=graph(e,s); b=project_roles(g)
    root=Path(__file__).parent/"patterns"
    k=read(root/"keeper_rescue.json"); a=read(root/"alternating_threats.json")
    r2a={"keeper_rescue":match_episodes(k,b),"alternating_threats":match_episodes(a,b),
         "alternating_threats_score_context":match_mixed_alternation(a,b)}
    r2bc=run(e,g,b,s,default_templates())
    return compile_pack(e,r2a,r2bc,legacy=legacy)

def comeback_fixture():
    e=fixture(atom("g1",100,"","Goal"),atom("g2",400,"","Goal"),atom("g3",700,"","Goal"),
              shot("a",200,1))
    return e,score((110,"0:1"),(410,"1:1"),(710,"2:1"))

class R3Tests(unittest.TestCase):
    def test_state_anchors_no_score_carrier_or_gap_media(self):
        e,s=comeback_fixture()
        b=pack(e,s)["stories"]["comeback:1"]
        self.assertEqual([x["event_ids"] for x in b["initial_edl"]],[["g1"],["g2"],["g3"]])
        self.assertEqual([(x["media_in"],x["media_out"]) for x in b["initial_edl"]],
                         [(99,101),(399,401),(699,701)])
        self.assertEqual(b["context_pool"][0]["event_ids"],["a"])
        self.assertFalse(b["context_pool"][0]["selected"])
        self.assertEqual(b["story_graph"]["nodes"][0]["score_beneficiary"],"team_2")
        self.assertEqual(b["story_graph"]["nodes"][0]["actor"],"team_1")
        self.assertTrue(all(x["preview_only"] and not x["first_live_verified"] for x in b["initial_edl"]))
    def test_missing_goal_has_no_material_but_observation(self):
        e=fixture(atom("g1",100,"","Goal"),atom("g3",700,"","Goal"))
        s=score((110,"0:1"),(410,"1:1"),(710,"2:1"))
        b=pack(e,s)["stories"]["comeback:1"]
        self.assertEqual(b["story_diagnostics"]["missing_required_nodes"],["score:2"])
        self.assertFalse(b["story_diagnostics"]["structurally_complete"])
        n=b["story_graph"]["nodes"][1]
        self.assertEqual(n["node_type"],"missing")
        self.assertFalse(n["material_ids"])
        self.assertTrue(any(t["task_type"]=="missing_goal_localization" for t in b["observation_tasks"]))
    def test_opening_state_has_no_material(self):
        e=fixture(atom("g",100,"","Goal"))
        b=pack(e,score((110,"1:0")))["stories"]["lead_preservation:1"]
        self.assertEqual(b["story_graph"]["nodes"][0]["node_type"],"transition")
        self.assertFalse(b["story_graph"]["nodes"][0]["material_ids"])
        self.assertEqual(len(b["initial_edl"]),1)
        self.assertTrue(any(d["kind"]=="lead_signature_requires_post_lead_defensive_evidence"
                            for d in b["story_diagnostics"]["diagnostics"]))
    def test_dual_view_context_dedup(self):
        e,s=comeback_fixture()
        d=atom("d",250,"1队球员发角球","Corner_kick")
        k=atom("k",252,"2队守门员扑救")
        e["atoms"].update(d=d,k=k)
        chain(e,["d","k"])
        b=pack(e,s)["stories"]["comeback:1"]
        c=next(x for x in b["context_pool"] if set(x["event_ids"])=={"d","k"})
        self.assertEqual({p["predicate"] for p in c["perspectives"]},{"attacking_threat","goalkeeper_rescue"})
        self.assertFalse(c["selected"])
    def test_same_event_multiple_stories_permitted(self):
        e,s=comeback_fixture()
        p=pack(e,s)
        c=p["stories"]["comeback:1"]; q=p["stories"]["equalization:1"]
        self.assertEqual(c["initial_edl"][0]["event_ids"],q["initial_edl"][0]["event_ids"])
    def test_relation_materializes_all_intermediate_members_no_gap_fill(self):
        e=fixture(atom("r",80,"2队球员抢断","Defensive_action"),
                  atom("p",85,"2队球员传球","Pass"),atom("s",90,"","Shot"),atom("g",92,"","Goal"))
        chain(e,["r","p","s","g"])
        b=pack(e,score((100,"0:1")))["stories"]["turnover_to_goal:1"]
        self.assertEqual({eid for x in b["initial_edl"] for eid in x["event_ids"]},{"r","p","s","g"})
        self.assertEqual([(x["media_in"],x["media_out"]) for x in b["initial_edl"]],
                         [(79,81),(84,86),(89,93)])
        self.assertTrue(any(n["node_type"]=="context" and n["event_ids"]==["p","s"] for n in b["story_graph"]["nodes"]))
    def test_phase_transition_search_not_clip(self):
        e=fixture(shot("a",10,1),shot("b",20,1),shot("c",40,2),shot("d",50,2))
        b=pack(e,score())["stories"]["threat_phase_change:1"]
        n=next(x for x in b["story_graph"]["nodes"] if x["node_id"]=="phase_switch")
        self.assertEqual(n["search_interval"],[21,39])
        self.assertFalse(n["material_ids"])
        self.assertEqual(len(b["initial_edl"]),4)
    def test_shared_material_multiple_node_roles_once(self):
        e=fixture(atom("a",10,"","Shot",window=[9,12]),atom("b",11,"","Save",window=[10,13]))
        root={"video_id":"v","input_tier":"RAW_EVENTS_ONLY","template_id":"t","category":"test",
              "subtype":"test","narrative_goal":["test"]}
        c={"candidate_id":"t:1","subjects":["team_1","team_2"],
           "nodes":[{"node_id":"x","event_ids":["a","b"],"media_windows":[[9,13]],"actor_role":"attacking_team"},
                    {"node_id":"y","event_ids":["b"],"media_windows":[[10,13]],"actor_role":"goalkeeper_team"}],
           "edges":[{"from":"x","to":"y","relation":"temporal_episode_order"}]}
        g=compile_story(root,c,"alternate",{})
        b=materialize(g,e,{})
        self.assertEqual(len(b["initial_edl"]),1)
        self.assertEqual(b["initial_edl"][0]["event_ids"],["a","b"])
        self.assertEqual(b["initial_edl"][0]["story_node_ids"],["x","y"])
    def test_nonlive_or_forged_window_rejected(self):
        e,s=comeback_fixture()
        p=pack(e,s)
        g=p["stories"]["comeback:1"]["story_graph"]
        g=deepcopy(g); g["nodes"][0]["media_windows"]=[[0,101]]
        with self.assertRaises(ValueError):
            materialize(g,e,{})
        g=p["stories"]["comeback:1"]["story_graph"]
        e["atoms"]["g1"]["broadcast_phase"]="REPLAY"
        with self.assertRaises(ValueError):
            materialize(g,e,{})
    def test_legacy_seed_byte_preserved_and_separate(self):
        e,s=comeback_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            raw=b'[\n {"media_in":90,"media_out":105}, {"media_in":190,"media_out":210}\n]\n'
            (d/"native.json").write_bytes(raw)
            manifest={"schema":"sportscausal_legacy_seed_manifest_v1","seeds":[
                {"story_id":"comeback:1","video_id":"v","subjects":["team_1"],"path":"native.json",
                 "sha256":hashlib.sha256(raw).hexdigest(),"source_provenance":"synthetic unit fixture"}]}
            (d/"manifest.json").write_text(json.dumps(manifest))
            legacy=load_seed_manifest(d/"manifest.json")
            p=pack(e,s,legacy)
            write_pack(d/"out",p,legacy)
            folder=d/"out"/"comeback__1"
            self.assertEqual((folder/"legacy_seed.json").read_bytes(),raw)
            self.assertEqual(len(read(folder/"initial_edl.json")),3)
            self.assertEqual(read(folder/"story_graph.json")["agent_seed"]["file"],"legacy_seed.json")
            manifest["seeds"][0]["sha256"]="wrong"
            (d/"manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                load_seed_manifest(d/"manifest.json")
    def test_no_seed_explicit_status(self):
        e,s=comeback_fixture()
        b=pack(e,s)["stories"]["comeback:1"]
        self.assertEqual(b["legacy_seed"]["status"],"legacy_seed_not_supplied")
        self.assertEqual(b["story_graph"]["agent_seed"]["file"],"initial_edl.json")
    def test_mixed_hypothesis_retains_ineligible_flag(self):
        e=fixture(shot("a",10,1),atom("g",300,"","Goal"),shot("b",600,1))
        b=pack(e,score((310,"0:1")))["stories"]["alternating_threats_score_context:1"]
        self.assertFalse(b["story_graph"]["strict_threat_metric_eligible"])
        self.assertEqual(b["story_graph"]["nodes"][1]["actor_role"],"score_beneficiary")

if __name__=="__main__":
    unittest.main()
