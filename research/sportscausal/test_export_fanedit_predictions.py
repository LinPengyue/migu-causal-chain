import unittest
from export_fanedit_predictions import project, story_rows, causal_rows

V="FH-TEST-V1"
B={"video_id":V,"native_video_id":"source"}
VIDEO={"match_id":"FH-TEST","duration_sec":100,"causal_eval_source":True}
EVENTS={V+":E:e1":{"video_id":V,"start_sec":10,"end_sec":12},
        V+":E:e2":{"video_id":V,"start_sec":20,"end_sec":24}}
TAX={"story":{"人物故事链":["同队门将多次化险"]},
     "causal":{"结果链":["抢断/反击/失误后直接进球链","其他"]}}
def seg(ids,lo=10,hi=12,**kw):
    return {"media_in":lo,"media_out":hi,"event_ids":ids,**kw}
def story(*segments):
    return story_rows(list(segments),"keeper_rescue","keeper_rescue:2")[0]

class ExportTests(unittest.TestCase):
    def test_exact_native_mapping_and_bridge_inheritance(self):
        p,issues,excluded=project(story(seg(["e1"],video_id="source"),
            seg(["e2"],20,24,shot_kind="search_bridge")),"story",B,VIDEO,EVENTS,TAX,{})
        self.assertEqual(issues,[])
        self.assertEqual([s["event_ids"] for s in p["segments"]],[[V+":E:e1"],[V+":E:e2"]])
        self.assertEqual(excluded,[])
    def test_unknown_atom_and_wrong_time_retained(self):
        p,issues,_=project(story(seg(["atom_fill_1","e2"])),"story",B,VIDEO,EVENTS,TAX,{})
        self.assertEqual(len(p["segments"]),1)
        self.assertEqual(p["segments"][0]["event_ids"],[])
        self.assertEqual({x["reason"] for x in issues},
          {"UNMAPPED_NATIVE_EVENT","EVENT_OUTSIDE_PREDICTED_WINDOW","NO_EVAL_EVENT_IDS"})
    def test_foreign_source(self):
        _,issues,_=project(story(seg(["e1"],video_id="wrong")),"story",B,VIDEO,EVENTS,TAX,{})
        self.assertIn("FOREIGN_SOURCE",{x["reason"] for x in issues})
    def test_inactive_excluded_but_timed_replay_not_erased(self):
        p,issues,ex=project(story(seg(["e1"],include_in_cut=False),
            seg(["e2"],20,24,shot_kind="replay",is_replay=True)),"story",B,VIDEO,EVENTS,TAX,{})
        self.assertEqual(len(ex),1)
        self.assertEqual(len(p["segments"]),1)
        self.assertEqual(issues,[])
    def test_order_and_duplicate_preservation(self):
        p,issues,_=project(story(seg(["e2"],20,24),seg(["e1","e1"])),"story",B,VIDEO,EVENTS,TAX,{})
        self.assertEqual(issues,[])
        self.assertEqual([s["start_sec"] for s in p["segments"]],[20,10])
        self.assertEqual(p["segments"][1]["event_ids"],[V+":E:e1",V+":E:e1"])
    def test_causal_ms_and_unknown_label(self):
        doc={"schema":"v2_upstream_strip_json_v1","chains":[
            {"clip_id":"clip00","chain_category":"outcome","template_id":"turnover_counter_goal",
             "t0_ms":10000,"t1_ms":24000,"event_ids":["e1","e2"]},
            {"clip_id":"clip01","chain_category":"outcome","template_id":"unknown",
             "t0_ms":10000,"t1_ms":12000,"event_ids":["e1"]}]}
        a,b=causal_rows(doc,"strip831")
        p,issues,_=project(a,"causal",B,VIDEO,EVENTS,TAX,{})
        self.assertEqual(issues,[])
        self.assertEqual((p["start_sec"],p["end_sec"]),(10,24))
        _,issues,_=project(b,"causal",B,VIDEO,EVENTS,TAX,{})
        self.assertIn("UNMAPPED_TAXONOMY",{x["reason"] for x in issues})
    def test_adapted_requires_prediction_provenance(self):
        with self.assertRaises(ValueError):
            causal_rows({"causal_chains":[]},"adapted_causal")
    def test_no_fake_prediction_from_empty_edl(self):
        _,issues,_=project(story(),"story",B,VIDEO,EVENTS,TAX,{})
        self.assertIn("EMPTY_PREDICTED_STORY_OR_CHAIN",{x["reason"] for x in issues})

if __name__=="__main__":
    unittest.main()
