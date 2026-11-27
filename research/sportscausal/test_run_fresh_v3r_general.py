"""New-run orchestration regression; no real videos, no HTTP, no A/B reruns."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from copy import deepcopy

import run_fresh_v3r_general as entry
from template_graph import read, write

TEAMS = {"team_1": {"name": "甲队"}, "team_2": {"name": "乙队"}}
MAPPING = {"left": "team_2", "right": "team_1"}


def event(eid, t, phase="LIVE"):
    return {"event_id": eid, "event_type": "Save", "notes": "2队守门员扑救",
            "media_time": {"event_time_sec": t, "start_time_sec": t-1, "end_time_sec": t+1},
            "video_context": {"broadcast_phase": phase}, "attributes": {}}


class FreshEntryTests(unittest.TestCase):
    def test_mapping_reversed_and_native_conflict(self):
        self.assertEqual(entry.score_mapping({}, "team_2", "verified columns")[0], MAPPING)
        with self.assertRaises(ValueError):
            entry.score_mapping({"score_side_mapping": MAPPING}, "team_1", "other")
        with self.assertRaises(ValueError):
            entry.score_mapping({})
        with self.assertRaises(ValueError):
            entry.score_mapping({}, "team_2")

    def test_no_synthetic_score(self):
        s = entry.make_score_doc({"events": [], "teams": TEAMS}, "v", MAPPING, "fixture", lambda _: [])
        self.assertEqual(s["score_path"], [])
        self.assertEqual(s["score_side_mapping"], MAPPING)

    def test_reject_reference_and_duplicates(self):
        raw = {"teams": TEAMS, "events": [event("a", 10)]}
        for bad in ({**raw, "causal_chains": []}, {**raw, "story_chains": []},
                    {**raw, "events": [event("a", 10), event("a", 20)]}):
            with self.assertRaises(ValueError):
                entry.validate_native(bad)

    def exercise(self, mode, selected=None, fail_strip=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = {"teams": TEAMS, "events": [event("a", 10), event("b", 60)]}
            native = root / "native.json"
            source = root / "source.mp4"
            supplement = root / "supplement.json"
            out = root / "run"
            write(native, raw)
            write(supplement, {"fixture": True})
            source.write_bytes(b"mock video")
            argv = ["--match-json", str(native), "--source-mp4", str(source),
                    "--score-left-team", "team_2", "--score-mapping-provenance", "fixture",
                    "--out-dir", str(out)]
            if mode == "HUMAN_ATOM_ENRICHED_DEV":
                argv += ["--causal-atoms-json", str(supplement), "--allow-dev"]
            elif mode == "INDEPENDENT_ATOMIC_ANNOTATED":
                argv += ["--independent-atoms-json", str(supplement)]
            if selected:
                argv += ["--template-id", selected]
            args = entry.parser().parse_args(argv)
            calls = []

            def enrich_files(**kw):
                calls.append("enrich")
                self.assertEqual(bool(kw["causal_path"]), mode == "HUMAN_ATOM_ENRICHED_DEV")
                self.assertEqual(bool(kw["independent_atoms_path"]), mode == "INDEPENDENT_ATOMIC_ANNOTATED")
                enriched = deepcopy(raw)
                if mode != "RAW_EVENTS_ONLY":
                    extra = event("filled", 100)
                    extra["enrichment"] = {"provenance": "causal_atom_fill" if kw["causal_path"]
                                           else "independent_atomic_annotation"}
                    enriched["events"].append(extra)
                report = {"input_mode": mode, "source_causal_atoms_only": str(supplement) if kw["causal_path"] else None,
                          "independent_atomic_annotations_used": bool(kw["independent_atoms_path"]),
                          "source_independent_atoms": str(supplement) if kw["independent_atoms_path"] else None,
                          "eligible_for_raw_only_evaluation": mode == "RAW_EVENTS_ONLY",
                          "n_injected": len(enriched["events"])-2}
                write(kw["out_events_path"], enriched)
                write(kw["out_report_path"], report)
                return report

            def strip(enriched_path, **kw):
                calls.append("strip")
                self.assertEqual(kw["algo_root"], entry.DELIVERY)
                ids = [a["event_id"] for a in read(enriched_path)["events"]]
                self.assertEqual("filled" in ids, mode != "RAW_EVENTS_ONLY")
                if fail_strip:
                    raise RuntimeError("fixture failure")
                data = {"use_llm": False, "profile": "production", "n_events": len(ids), "n_chains": 0}
                write(kw["out_dir"] / "strip_A_original.json", data)
                return data

            def adapt(**kw):
                calls.append("adapt")
                self.assertTrue(kw["strip_path"].is_file())
                pred = {"v3_adapter": {"human_causal_structure_used": False}, "causal_chains": []}
                write(kw["out_path"], pred)
                write(kw["recovery_out_path"], {"candidates": []})
                return pred

            def score(events):
                calls.append("score")
                self.assertEqual(any(e["event_id"] == "filled" for e in events), mode != "RAW_EVENTS_ONLY")
                return []

            upstream = (SimpleNamespace(_run_strip=strip, _adapt_v1=adapt),
                        SimpleNamespace(enrich_files=enrich_files), SimpleNamespace(build_score_path=score))
            with patch.object(entry, "load_upstream", return_value=upstream), \
                 patch.object(entry, "probe_video", return_value=(200., {"streams": []})), \
                 patch.object(entry, "git", return_value="test"):
                if fail_strip:
                    with self.assertRaises(RuntimeError):
                        entry.run(args)
                    audit = read(out / "run_manifest.json")
                    self.assertEqual(audit["status"], "FAILED")
                    self.assertEqual(calls, ["enrich", "strip"])
                    self.assertFalse((out / "08_r3").exists())
                    return
                audit = entry.run(args)
                self.assertEqual(calls, ["enrich", "strip", "adapt", "score"])
                self.assertEqual(audit["status"], "COMPLETE")
                self.assertEqual(audit["input_tier"], mode)
                self.assertEqual(len(audit["stages"]), 8)
                ev = read(out / "04_evidence" / "evidence.json")
                self.assertEqual("filled" in ev["atoms"], mode != "RAW_EVENTS_ONLY")
                summary = read(out / "08_r3" / "summary.json")
                self.assertGreater(summary["template_counts"]["keeper_rescue"], 0)
                self.assertEqual(set(summary["template_counts"]), {selected} if selected else
                    {"keeper_rescue", "alternating_threats", "alternating_threats_score_context",
                     "comeback", "equalization", "lead_preservation", "set_piece_breakthrough",
                     "turnover_to_goal", "threat_phase_change"})
                self.assertFalse(summary["first_live_verified"])
                self.assertEqual(read(native), raw)
                with self.assertRaises(FileExistsError):
                    entry.run(args)

    def test_raw_full_pipeline(self):
        self.exercise("RAW_EVENTS_ONLY")

    def test_causal_atom_fill_full_pipeline(self):
        self.exercise("HUMAN_ATOM_ENRICHED_DEV")

    def test_independent_atom_fill_filtered_output(self):
        self.exercise("INDEPENDENT_ATOMIC_ANNOTATED", "keeper_rescue")

    def test_failure_is_not_complete(self):
        self.exercise("RAW_EVENTS_ONLY", fail_strip=True)


if __name__ == "__main__":
    unittest.main()
