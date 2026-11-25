import unittest
from evidence_representation import build_evidence, compact_request, bind_story

T={"template_id":"test","category":"test","subtype":"test","goal":"test",
   "slots":[{"slot_id":"save","purpose":"save","min_items":1,"max_items":3,"anchor":True}]}
R={"input_mode":"RAW_EVENTS_ONLY","eligible_for_raw_only_evaluation":True}

def ev(i,t,*,replay=False,provenance=None):
    return {"event_id":i,"event_type":"Save","notes":"2队守门员扑住1队射门",
            "attributes":{"Related_Player":["2队1号"]},
            "media_time":{"event_time_sec":t,"start_time_sec":t-1,"end_time_sec":t+1},
            "video_context":{"broadcast_phase":"REPLAY" if replay else "LIVE","is_replay":replay},
            "enrichment":{"provenance":provenance}}

def fixture():
    events={"teams":{"team_1":{"name":"A"},"team_2":{"name":"B"}},"events":[
        ev("a",10),ev("b",11),ev("c",30),ev("r",50,replay=True)]}
    pred={"v3_adapter":{},"causal_chains":[
        {"annotation_id":"p","events":[{"event_id":i} for i in ["a","c","r"]]},
        {"annotation_id":"q","events":[{"event_id":"r"}]},
        {"annotation_id":"z","is_replay":True,"events":[{"event_id":"a"}]}]}
    return events,pred

def sel(ids,cids=()):
    return {"bindings":[{"slot_id":"save","instances":[{"event_ids":ids,"chain_ids":list(cids)}]}]}

class Tests(unittest.TestCase):
    def setUp(self):
        self.events,self.pred=fixture()
        self.e=build_evidence(self.events,self.pred,R,video_id="v",duration_sec=60)

    def test_preserve_attributes_and_notes(self):
        req=compact_request(T,self.e)
        self.assertEqual(len(req["events"]),3)
        row=dict(zip(req["event_columns"],req["events"][0]))
        self.assertEqual(row["notes"],"2队守门员扑住1队射门")
        self.assertEqual(row["attributes"]["Related_Player"],["2队1号"])
        self.assertEqual(req["source"]["teams"]["team_2"]["name"],"B")

    def test_partial_not_full_and_no_replay(self):
        self.assertEqual(self.e["chains"]["p"]["state"],"PARTIAL")
        self.assertEqual(self.e["chains"]["q"]["state"],"UNAVAILABLE")
        self.assertEqual(self.e["chains"]["z"]["state"],"NONLIVE_CHAIN")
        self.assertEqual([r[0] for r in compact_request(T,self.e)["predicted_chains"]],["p"])
        self.assertNotIn("r",self.e["atoms"])

    def test_overlap_union_and_no_gap_fill(self):
        r=bind_story(T,self.e,sel(["a","b","c"],["p"]))
        self.assertEqual([(x["media_in"],x["media_out"]) for x in r["candidate_edl"]],[(9,12),(29,31)])
        self.assertEqual([x["story_anchor"] for x in r["candidate_edl"]],[False,True])
        self.assertFalse(r["quality_verified"])
        self.assertFalse(r["release_authorized"])

    def test_reject_bad_bindings(self):
        for ids,cids in [(["r"],[]),(["b"],["p"]),(["a"],["z"]),(["a","a"],[])]:
            with self.subTest(ids=ids,cids=cids),self.assertRaises(ValueError):
                bind_story(T,self.e,sel(ids,cids))

    def test_dev_provenance(self):
        self.events["events"][0]["enrichment"]["provenance"]="causal_atom_fill"
        with self.assertRaises(ValueError):
            build_evidence(self.events,self.pred,R,video_id="v",duration_sec=60)
        e=build_evidence(self.events,self.pred,R,video_id="v",duration_sec=60,allow_dev=True)
        self.assertEqual(e["input_tier"],"HUMAN_ATOM_ENRICHED_DEV")

    def test_legacy_report_and_unknown(self):
        for report,tier in [({"source_causal_atoms_only":"old_causal.json"},"HUMAN_ATOM_ENRICHED_DEV"),
                            ({"n_raw_events":4},"UNCONFIRMED_PROVENANCE_DEV")]:
            with self.assertRaises(ValueError):
                build_evidence(self.events,self.pred,report,video_id="v",duration_sec=60)
            e=build_evidence(self.events,self.pred,report,video_id="v",duration_sec=60,allow_dev=True)
            self.assertEqual(e["input_tier"],tier)

if __name__=="__main__":
    unittest.main()
