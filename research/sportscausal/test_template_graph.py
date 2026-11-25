"""Synthetic contract tests, no API calls and no reference data."""
import copy
import json
import unittest
from pathlib import Path
from template_graph import make_inventory, instantiate, planner_request, validate_template

ROOT = Path(__file__).parent


def event(i, t, replay=False):
    return {"event_id": i, "event_type": "Save", "media_time": {
        "event_time_sec": t, "start_time_sec": t-1, "end_time_sec": t+1},
        "video_context": {"broadcast_phase": "REPLAY" if replay else "LIVE", "is_replay": replay}}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((ROOT / "templates/keeper_rescue.json").read_text())
        self.events = {"events": [event("a", 10), event("b", 20), event("c", 30, True), event("d", 40)]}
        self.causal = {"v3_adapter": {}, "causal_chains": [
            {"annotation_id": "p1", "events": [{"event_id": "a"}]},
            {"annotation_id": "p2", "events": [{"event_id": "b"}, {"event_id": "c"}]},
            {"annotation_id": "p3", "events": [{"event_id": "missing"}]}]}
        self.inv = make_inventory(self.events, self.causal, video_id="v", duration_sec=60)

    def select(self, ids):
        return {"bindings": [{"slot_id": "save", "material_ids": ids}]}

    def test_replay_and_unbound_chain_excluded(self):
        self.assertNotIn("event:c", self.inv["materials"])
        self.assertNotIn("chain:p2", self.inv["materials"])
        self.assertNotIn("chain:p3", self.inv["materials"])

    def test_repeated_role_and_source_binding(self):
        r = instantiate(self.template, self.inv, self.select(["chain:p1", "event:b"]))
        self.assertTrue(r["structurally_complete"])
        self.assertFalse(r["release_authorized"])
        self.assertFalse(r["first_live_verified"])
        self.assertEqual([x["media_in"] for x in r["candidate_edl"]], [9, 19])
        self.assertEqual(len({x["segment_id"] for x in r["candidate_edl"]}), 2)
        self.assertTrue(all(x["story_anchor"] for x in r["candidate_edl"]))
        self.assertEqual(r["candidate_edl"][0]["short_chain_ids"], ["p1"])
        self.assertFalse(r["story_graph"]["edges"][0]["causal_verified"])

    def test_missing_slots_reported_without_fabrication(self):
        r = instantiate(self.template, self.inv, self.select(["event:a"]))
        self.assertFalse(r["structurally_complete"])
        self.assertEqual(len(r["candidate_edl"]), 1)
        self.assertEqual(r["missing_required_slots"][0]["slot_id"], "save")

    def test_bad_bindings(self):
        for ids in (["event:unknown"], ["event:c"], ["event:a", "chain:p1"],
                    ["event:b", "event:a"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                instantiate(self.template, self.inv, self.select(ids))
        bad = self.select(["event:a"])
        bad["bindings"][0]["media_in"] = 0
        with self.assertRaises(ValueError):
            instantiate(self.template, self.inv, bad)

    def test_template_generic(self):
        for name, slots in (("set_piece_breakthrough", ["execution", "result"]),
                            ("alternating_threats", ["threat", "threat"])):
            t = json.loads((ROOT / "templates" / (name + ".json")).read_text())
            validate_template(t)
            s = {"bindings": []}
            for sid, mid in zip(slots, ["event:a", "event:b"]):
                row = next((r for r in s["bindings"] if r["slot_id"] == sid), None)
                if row is None:
                    row = {"slot_id": sid, "material_ids": []}
                    s["bindings"].append(row)
                row["material_ids"].append(mid)
            self.assertTrue(instantiate(t, self.inv, s)["structurally_complete"])
            self.assertEqual(planner_request(t, self.inv)["template"]["template_id"], name)

    def test_no_reference_document(self):
        with self.assertRaises(ValueError):
            make_inventory(self.events, {"causal_chains": []}, video_id="v", duration_sec=60)


if __name__ == "__main__":
    unittest.main()
