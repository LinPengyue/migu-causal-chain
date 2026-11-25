"""Offline evaluator regression checks. Reference-as-prediction is NOT a model result."""
import argparse
import copy
import json
from pathlib import Path
from evaluate import evaluate, read, assignment, threshold_match, score_group, THRESHOLDS, DEFAULT_DATA


def main(data):
    data = Path(data)
    assert assignment([[0.9, 0.8], [0.8, 0.0]]) == [(0, 1), (1, 0)]
    assert len(threshold_match([[0.9, 0.5], [0.5, 0.0]], 0.5)) == 2
    assert assignment([[], []]) == []
    def story(a, b, ids=("e",), v="v", sub="s"):
        return {"category": "c", "subtype": sub,
                "segments": [{"video_id": v, "start_sec": a, "end_sec": b, "event_ids": list(ids)}]}
    g = story(0, 10)
    r = score_group([story(0, 4)], [g], "story", THRESHOLDS, 0.5)
    assert list(r["story_tp"].values()) == [1, 0, 0]
    assert list(r["segment_tp"].values()) == [1, 0, 0]
    assert abs(r["iou_sum"] - 0.4) < 1e-12
    for p in (story(0, 10, v="other"), story(0, 10, sub="wrong")):
        r = score_group([p], [g], "story", THRESHOLDS, 0.5)
        assert r["iou_sum"] == r["event_sum"] == 0
    a = {"category": "c", "subtype": "s", "video_id": "v", "start_sec": 0,
         "end_sec": 10, "event_ids": ["a", "b"]}
    b = dict(a, event_ids=["x", "y"])
    assert all(not x for x in score_group([a], [b], "causal", THRESHOLDS, 0.5).values())
    report = {}
    matches = read(data / "matches.jsonl")
    logs = [{"match_id": m["match_id"], "elapsed_sec": 60, "api_cost_usd": 0.25} for m in matches]
    for task, count in (("causal", 750), ("story", 173)):
        refs = read(data / (task + "_chains.jsonl"))
        full = evaluate(data, task, refs, run_log=logs)
        empty = evaluate(data, task, [])
        dup = evaluate(data, task, refs + [refs[0]])
        dev = evaluate(data, task, refs, exclude_known_dev=True, run_log=logs)
        partial = evaluate(data, task, [], run_log=logs[:1])
        assert full["matches"] == 84 and full["references"] == count
        assert dev["matches"] == 80
        assert full["efficiency"]["time_min_per_match"] == 1
        assert full["efficiency"]["api_cost_usd_per_match"] == 0.25
        assert partial["efficiency"]["time_min_per_match"] is None
        for t in map(str, THRESHOLDS):
            f, z, d = (x["by_threshold"][t] for x in (full, empty, dup))
            if task == "story":
                assert f["story_recall"] == 1 and z["story_recall"] == 0
                f, z, d = f["segment"], z["segment"], d["segment"]
            assert f["f1"] == 1 and z["f1"] == 0 and d["f1"] < 1
        if task == "story":
            assert full["reference_segments"] == 1536
            assert full["miou"] == full["event_f1"] == 1
            assert empty["miou"] == empty["event_f1"] == 0
            assert dup["miou"] < 1 and dup["event_f1"] < 1
        bad = copy.deepcopy(refs[0])
        seg = bad if task == "causal" else bad["segments"][0]
        seg["start_sec"] = 0
        seg["end_sec"] = 0.01
        try:
            evaluate(data, task, [bad])
        except ValueError:
            pass
        else:
            raise AssertionError("Out-of-window event accepted")
        report[task] = {"references": count, "self_match_all_thresholds": 1,
                        "empty_all_thresholds": 0, "duplicate_penalized": True,
                        "excluded_known_dev_matches": 80, "efficiency_log_checks": True}
    print(json.dumps({"status": "PASS", "tests": report}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default=str(DEFAULT_DATA))
    main(p.parse_args().data_dir)
