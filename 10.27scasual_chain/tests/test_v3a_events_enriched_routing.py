"""Regression: Search must prefer V3-R events_enriched.json over raw 赛事.json."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_e2e_agent import (
    resolve_events_json_for_agent,
)
from story_video_agent_v3.story_evidence_search import (
    load_match_events,
    run_story_evidence_search,
)


def _write(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class TestEventsEnrichedRouting(unittest.TestCase):
    def test_raw_events_json_does_not_bypass_phase5_sibling_enrich(self):
        root = Path(tempfile.mkdtemp(prefix="p8_enrich_route_"))
        raw = _write(
            root / "match_raw.json",
            {
                "events": [
                    {
                        "event_id": "raw_only",
                        "event_type": "Pass",
                        "media_time": {
                            "event_time_sec": 100.0,
                            "start_time_sec": 99.0,
                            "end_time_sec": 102.0,
                        },
                        "video_context": {
                            "broadcast_phase": "LIVE",
                            "is_replay": False,
                        },
                    }
                ]
            },
        )
        enriched = _write(
            root / "01_to_04" / "01_enrich" / "events_enriched.json",
            {
                "events": [
                    {
                        "event_id": "raw_only",
                        "event_type": "Pass",
                        "media_time": {
                            "event_time_sec": 100.0,
                            "start_time_sec": 99.0,
                            "end_time_sec": 102.0,
                        },
                        "video_context": {
                            "broadcast_phase": "LIVE",
                            "is_replay": False,
                        },
                    },
                    {
                        "event_id": "atom_fill_0000_Goal_200000",
                        "event_type": "Goal",
                        "media_time": {
                            "event_time_sec": 200.0,
                            "start_time_sec": 199.0,
                            "end_time_sec": 205.0,
                        },
                        "video_context": {
                            "broadcast_phase": "LIVE",
                            "is_replay": False,
                        },
                        "enrichment": {"provenance": "causal_atom_fill"},
                    },
                ]
            },
        )
        phase5 = root / "01_to_04" / "04_phase5"
        phase5.mkdir(parents=True, exist_ok=True)

        resolved = resolve_events_json_for_agent(
            events_json=raw,  # deliberately raw — must not win
            phase5_dir=phase5,
            out_dir=None,
        )
        self.assertEqual(Path(resolved).resolve(), enriched.resolve())

        rows = load_match_events(match_json=raw, events_json=resolved)
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(r.get("event_id", "").startswith("atom_fill_") for r in rows))

        # End-to-end search path uses resolved enrich (879-style atom fills available).
        diag = {
            "schema": "v3a_story_diagnosis_v1",
            "story_diagnosis_valid": True,
            "issues": [
                {
                    "issue_id": "missing_pre_goal_buildup",
                    "severity": "major",
                    "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                    "story_defect_confirmed": True,
                    "evidence_sufficiency": "observed",
                    "needed_evidence_types": ["shot", "goal", "buildup"],
                    "summary": "Need pre-goal buildup from source",
                }
            ],
        }
        report = run_story_evidence_search(
            diagnosis=diag,
            edl=[],
            match_json=raw,
            events_json=resolved,
        )
        self.assertEqual(report.get("events_loaded"), 2)
        self.assertTrue(str(report.get("events_json") or "").endswith("events_enriched.json"))

    def test_explicit_enriched_path_still_accepted(self):
        root = Path(tempfile.mkdtemp(prefix="p8_enrich_explicit_"))
        enriched = _write(
            root / "custom" / "events_enriched.json",
            {"events": [{"event_id": "e1", "event_type": "Shot",
                         "media_time": {"event_time_sec": 1.0, "start_time_sec": 0.5, "end_time_sec": 2.0},
                         "video_context": {"broadcast_phase": "LIVE", "is_replay": False}}]},
        )
        resolved = resolve_events_json_for_agent(events_json=enriched, phase5_dir=None)
        self.assertEqual(Path(resolved).resolve(), enriched.resolve())


if __name__ == "__main__":
    unittest.main()
