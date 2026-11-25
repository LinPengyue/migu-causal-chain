"""FanEdit evaluator v2; frozen v1.1 references, provisional diagnostic scores."""
import argparse
import collections
import json
import math
from pathlib import Path

THRESHOLDS = (0.3, 0.5, 0.7)
DEFAULT_DATA = Path(__file__).resolve().parent.parent / "v1.1"


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def ratio(a, b):
    return a / b if b else 0.0


def label(x):
    return x["category"], x["subtype"]


def segments(x, task):
    return [x] if task == "causal" else x["segments"]


def intervals(x, task):
    d = collections.defaultdict(list)
    for s in segments(x, task):
        d[s["video_id"]].append((s["start_sec"], s["end_sec"]))
    out = {}
    for v, xs in d.items():
        merged = []
        for a, b in sorted(xs):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        out[v] = merged
    return out


def tiou(a, b):
    inter = sum(max(0, min(y, v) - max(x, u))
                for k in a.keys() & b.keys()
                for x, y in a[k] for u, v in b[k])
    total = sum(y - x for d in (a, b) for xs in d.values() for x, y in xs)
    return ratio(inter, total - inter)


def event_set(x, task):
    return {i for s in segments(x, task) for i in s["event_ids"]}


def event_f1(a, b):
    return ratio(2 * len(a & b), len(a) + len(b))


def assignment(weights):
    """Maximum-weight one-to-one matching, zero-weight edges discarded.
    Rectangular Hungarian algorithm with zero dummy columns/rows, O(n^3).
    """
    n = len(weights)
    m = len(weights[0]) if n else 0
    if not n or not m:
        return []
    size = max(n, m)
    u, v = [0.0] * (size + 1), [0.0] * (size + 1)
    p, way = [0] * (size + 1), [0] * (size + 1)
    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        mins = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = float("inf"), 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                w = weights[i0 - 1][j - 1] if i0 <= n and j <= m else 0.0
                cur = -w - u[i0] - v[j]
                if cur < mins[j]:
                    mins[j], way[j] = cur, j0
                if mins[j] < delta:
                    delta, j1 = mins[j], j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    mins[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    return sorted((p[j] - 1, j - 1) for j in range(1, m + 1)
                  if 0 < p[j] <= n and weights[p[j] - 1][j - 1] > 0)


def threshold_match(scores, threshold, allowed=None):
    # Cardinality first; total IoU breaks ties. Forbidden edges have zero weight.
    bonus = max(len(scores), len(scores[0]) if scores else 0) + 1
    return assignment([[bonus + s if s >= threshold and
                        (allowed is None or allowed[i][j]) else 0.0
                        for j, s in enumerate(row)] for i, row in enumerate(scores)])


def prf(tp, np, ng):
    return {"tp": tp, "precision": ratio(tp, np), "recall": ratio(tp, ng),
            "f1": ratio(2 * tp, np + ng)}


def score_group(ps, gs, task, thresholds, event_threshold):
    pi, gi = [intervals(x, task) for x in ps], [intervals(x, task) for x in gs]
    pe, ge = [event_set(x, task) for x in ps], [event_set(x, task) for x in gs]
    ts = [[tiou(a, b) for b in gi] for a in pi]
    es = [[event_f1(a, b) for b in ge] for a in pe]
    same = [[label(p) == label(g) for g in gs] for p in ps]
    if task == "causal":
        allowed = [[same[i][j] and es[i][j] >= event_threshold
                    for j in range(len(gs))] for i in range(len(ps))]
        return {t: threshold_match(ts, t, allowed) for t in thresholds}
    # Fixed, threshold-independent story association for segment and soft metrics.
    # Story recall independently uses maximum cardinality at each threshold.
    pairs = assignment([[s if same[i][j] else 0.0 for j, s in enumerate(row)]
                        for i, row in enumerate(ts)])
    segment_tp = dict.fromkeys(thresholds, 0)
    for i, j in pairs:
        a = [intervals(s, "causal") for s in ps[i]["segments"]]
        b = [intervals(s, "causal") for s in gs[j]["segments"]]
        ss = [[tiou(x, y) for y in b] for x in a]
        for t in thresholds:
            segment_tp[t] += len(threshold_match(ss, t))
    return {"segment_tp": segment_tp,
            "story_tp": {t: len(threshold_match(ts, t, same)) for t in thresholds},
            "iou_sum": sum(ts[i][j] for i, j in pairs),
            "event_sum": sum(es[i][j] for i, j in pairs),
            "paired_stories": len(pairs)}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def efficiency(rows, matches, selected):
    if rows is None:
        return {"time_min_per_match": None, "api_cost_usd_per_match": None,
                "logged_matches": 0, "complete": False}
    logs = {}
    for r in rows:
        m = r["match_id"]
        require(m in matches and m not in logs, "Unknown/duplicate run-log match: " + m)
        for k in ("elapsed_sec", "api_cost_usd"):
            require(finite(r[k]) and r[k] >= 0, "Invalid run-log " + k)
        logs[m] = r
    covered = selected & logs.keys()
    complete = bool(selected) and covered == selected
    return {"time_min_per_match": sum(logs[m]["elapsed_sec"] for m in covered) / (60 * len(selected)) if complete else None,
            "api_cost_usd_per_match": sum(logs[m]["api_cost_usd"] for m in covered) / len(selected) if complete else None,
            "logged_matches": len(covered), "complete": complete}


def evaluate(data, task, pred, thresholds=THRESHOLDS, event_threshold=0.5,
             exclude_known_dev=False, run_log=None):
    require(task in ("causal", "story"), "Unknown task")
    thresholds = tuple(sorted(set(thresholds)))
    require(bool(thresholds) and all(finite(t) and 0 < t <= 1 for t in thresholds),
            "Invalid thresholds")
    require(finite(event_threshold) and 0 < event_threshold <= 1, "Invalid event threshold")
    d = Path(data)
    videos = {v["video_id"]: v for v in read(d / "videos.jsonl")}
    events = {e["event_id"]: e for e in read(d / "atomic_events.jsonl")}
    matches = {m["match_id"]: m for m in read(d / "matches.jsonl")}
    ref = read(d / (task + "_chains.jsonl"))
    vocab = json.loads((d / "taxonomy.json").read_text(encoding="utf-8"))[task]
    allowed = {(a, b) for a, bs in vocab.items() for b in bs}
    selected = {m for m, x in matches.items()
                if not exclude_known_dev or x["development_exposure"] != "known_development"}
    eligible = {v for v, x in videos.items() if task == "story" or x["causal_eval_source"]}
    gp, gg = collections.defaultdict(list), collections.defaultdict(list)
    excluded = 0
    for j, x in enumerate(pred):
        m = x["match_id"]
        require(m in matches, f"Unknown match at prediction {j}")
        if m not in selected:
            excluded += 1
            continue
        require(label(x) in allowed, f"Invalid taxonomy at prediction {j}")
        ss = segments(x, task)
        require(bool(ss), f"Empty segments at prediction {j}")
        for s in ss:
            v, lo, hi = s["video_id"], s["start_sec"], s["end_sec"]
            require(v in eligible and videos[v]["match_id"] == m, f"Invalid video at prediction {j}")
            require(finite(lo) and finite(hi) and 0 <= lo < hi <= videos[v]["duration_sec"],
                    f"Invalid interval at prediction {j}")
            ids = s["event_ids"]
            require(isinstance(ids, list) and bool(ids),
                    f"Empty/invalid event IDs at prediction {j}")
            require(all(i in events and events[i]["video_id"] == v and
                        min(hi, events[i]["end_sec"]) > max(lo, events[i]["start_sec"])
                        for i in ids), f"Invalid/out-of-window event ID at prediction {j}")
        gp[m].append(x)
    for x in ref:
        if x["match_id"] in selected:
            gg[x["match_id"]].append(x)
    ps = [x for m in sorted(selected) for x in gp[m]]
    gs = [x for m in sorted(selected) for x in gg[m]]
    np, ng = len(ps), len(gs)
    pc, gc = collections.Counter(map(label, ps)), collections.Counter(map(label, gs))
    result = {"protocol": "fanedit-eval-v2", "status": "PROVISIONAL_DIAGNOSTIC_NOT_GOLD",
              "task": task, "matches": len(selected), "predictions": np, "references": ng,
              "ignored_known_development_predictions": excluded,
              "thresholds": list(thresholds),
              "efficiency": efficiency(run_log, matches, selected)}
    groups = [(gp[m], gg[m], score_group(gp[m], gg[m], task, thresholds, event_threshold))
              for m in sorted(selected)]
    by_threshold = {}
    if task == "causal":
        result["event_f1_threshold"] = event_threshold
        for t in thresholds:
            tp = collections.Counter(label(p[i]) for p, g, r in groups for i, j in r[t])
            rows = [{"category": k[0], "subtype": k[1], "pred": pc[k], "ref": gc[k],
                     **prf(tp[k], pc[k], gc[k])} for k in sorted(pc.keys() | gc.keys())]
            by_threshold[str(t)] = {**prf(sum(tp.values()), np, ng),
                                    "macro_f1": ratio(sum(x["f1"] for x in rows), len(rows)),
                                    "by_type": rows}
    else:
        nps = sum(len(x["segments"]) for x in ps)
        ngs = sum(len(x["segments"]) for x in gs)
        result.update({"predicted_segments": nps, "reference_segments": ngs,
                       "paired_stories": sum(r["paired_stories"] for p, g, r in groups),
                       "miou": ratio(sum(r["iou_sum"] for p, g, r in groups), max(np, ng)),
                       "event_f1": ratio(2 * sum(r["event_sum"] for p, g, r in groups), np + ng)})
        for t in thresholds:
            stp = sum(r["segment_tp"][t] for p, g, r in groups)
            rtp = sum(r["story_tp"][t] for p, g, r in groups)
            by_threshold[str(t)] = {"segment": prf(stp, nps, ngs),
                                    "story_recall": ratio(rtp, ng), "story_tp": rtp}
    result["by_threshold"] = by_threshold
    result["caveat"] = "Non-exhaustive provisional references; not human narrative or first-live evaluation."
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default=str(DEFAULT_DATA))
    p.add_argument("--task", required=True, choices=["causal", "story"])
    p.add_argument("--pred", required=True)
    t = p.add_mutually_exclusive_group()
    t.add_argument("--thresholds", nargs="+", type=float, default=THRESHOLDS)
    t.add_argument("--tiou", type=float, help="Legacy single-threshold option")
    p.add_argument("--event-threshold", type=float, default=0.5)
    p.add_argument("--exclude-known-dev", action="store_true")
    p.add_argument("--run-log", help="JSONL: match_id, elapsed_sec, api_cost_usd")
    p.add_argument("--out")
    a = p.parse_args()
    result = evaluate(a.data_dir, a.task, read(a.pred),
                      [a.tiou] if a.tiou is not None else a.thresholds,
                      a.event_threshold, a.exclude_known_dev,
                      read(a.run_log) if a.run_log else None)
    s = json.dumps(result, ensure_ascii=False, indent=2)
    print(s)
    if a.out:
        Path(a.out).write_text(s + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
