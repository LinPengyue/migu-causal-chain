import json
import tempfile
import unittest
from pathlib import Path
from evidence_representation import build_evidence
from story_graph_planner import messages_for,validate_and_bind,run,parse_response
from test_evidence_representation import fixture,T,R

def proposal(ids=("a","c")):
    return {"title":"Keeper context","protagonist":"team 2","summary":"A possible repeated-save story",
            "no_story_reason":"","bindings":[{"slot_id":"save","instances":[
                {"event_ids":[i],"chain_ids":["p"],"narrative":"A save","link_from_previous":"" if j==0 else "another save"}
                for j,i in enumerate(ids)]}]}

class PlannerTests(unittest.TestCase):
    def setUp(self):
        events,chains=fixture()
        self.e=build_evidence(events,chains,R,video_id="v",duration_sec=60)

    def test_prompt_schema(self):
        m=messages_for(T,self.e)
        self.assertEqual([x["role"] for x in m],["system","user"])
        self.assertNotIn("instruction",json.loads(m[1]["content"]))
        self.assertIn("link_from_previous",m[0]["content"])

    def test_candidate_graph(self):
        r=validate_and_bind(T,self.e,proposal())
        self.assertEqual(r["status"],"CANDIDATE")
        self.assertEqual(len(r["story_graph"]["nodes"]),2)
        self.assertEqual(r["story_graph"]["edges"][0]["narrative_link_hypothesis"],"another save")
        self.assertFalse(r["story_graph"]["edges"][0]["causal_verified"])
        self.assertFalse(r["quality_verified"])

    def test_invalid_id(self):
        with self.assertRaises(ValueError):
            validate_and_bind(T,self.e,proposal(("r",)))

    def test_no_candidate(self):
        r=validate_and_bind(T,self.e,{"title":"","protagonist":"","summary":"","no_story_reason":"no evidence","bindings":[]})
        self.assertEqual(r["status"],"NO_CANDIDATE")

    def test_offline_run(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"run"
            r=run(T,self.e,out,response=proposal())
            self.assertEqual(r["mode"],"OFFLINE_RESPONSE")
            self.assertEqual(r["api_usage"]["http_attempts"],0)
            self.assertTrue((out/"candidate_edl.json").is_file())

    def test_invalid_response_no_retry(self):
        class Fake:
            calls=0
            def chat(self,**kwargs):
                self.calls+=1
                return {"content":"{","provider_mode":"real","finish_reason":"length"}
        api=Fake()
        with tempfile.TemporaryDirectory() as d:
            r=run(T,self.e,Path(d)/"run",api=api)
            self.assertEqual(r["status"],"FAILED")
            self.assertEqual(api.calls,1)
            self.assertFalse((Path(d)/"run"/"candidate_edl.json").exists())

if __name__=="__main__":
    unittest.main()
