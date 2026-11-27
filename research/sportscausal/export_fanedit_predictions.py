"""Post-inference export: lossless native predictions + strict FanEdit v1.1 projection.

This utility NEVER imports the agent or reads story_chains/causal_chains reference
files. It uses the frozen public taxonomy, source inventory and atomic ID catalog
only after predictions are frozen. One immutable output folder per export.
Unmappable predictions block strict projection; no silently dropping segments,
inventing event IDs, substituting previews for official output, or scoring.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

BENCHMARK_REF = "e67d7c9f596db5b3cd5618f4692733126e68b1c1"
EVAL_REF = "db25a77fe7d6b66f28abf8e9ae20ade67df1be98"
PINNED = {
    "videos.jsonl": "86568db1776bd44b4b1619f7f3c9aa7fcc65d01c801bc998efdcb972f04577e1",
    "atomic_events.jsonl": "ef6532da23a24636e033affd438d7528a464eaf68755457f922a59d76f2266a3",
    "taxonomy.json": "f9f717a57b3cae6d52178ec9c64d875c1ac133adbe2b1b32b5246a37937c80cf",
}
STORY_LABELS = {
    "comeback": ("战局故事链", "逆风翻盘"),
    "equalization": ("战局故事链", "落后追平"),
    "lead_preservation": ("战局故事链", "领先守成"),
    "keeper_rescue": ("人物故事链", "同队门将多次化险"),
    "alternating_threats": ("攻防战术故事链", "双方交替威胁"),
    "threat_phase_change": ("攻防战术故事链", "攻势换手"),
    "set_piece_breakthrough": ("关键转折故事链", "定位球战术执行与破局"),
    "turnover_to_goal": ("关键转折故事链", "攻守转换与关键破门"),
}
# Exact public type definitions, NOT inferred from matching reference labels.
# Unlisted/ambiguous detector templates need an explicit reviewed mapping.
CAUSAL_LABELS = {
    ("outcome", "corner_coop_goal"): ("结果链", "角球传中进球链"),
    ("outcome", "rebound_follow_up_goal"): ("结果链", "射门被扑后补射进球链"),
    ("outcome", "turnover_counter_goal"): ("结果链", "抢断/反击/失误后直接进球链"),
    ("outcome", "outcome_other"): ("结果链", "其他"),
    ("danger", "shot_save_chain"): ("险情链", "射门扑救链"),
    ("danger", "second_phase_after_frame_chain"): ("险情链", "门框后二次进攻链"),
    ("danger", "goal_line_extreme_save_chain"): ("险情链", "门线极限救险链"),
    ("correction", "goal_disallowed_chain"): ("修正链", "进球无效链"),
    ("correction", "var_overturn_chain"): ("修正链", "VAR改判链"),
    ("special", "quick_restart_set_piece_chain"): ("特殊链", "快发定位球链"),
}
CAT_ALIAS = {"结果链":"outcome", "险情链":"danger", "修正链":"correction", "特殊链":"special"}
STAGES = {"r3_initial", "agent_v0", "agent_preview", "agent_native_final",
          "strip831", "adapted_causal"}


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def write_lines(path, rows):
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False)+"\n" for row in rows), encoding="utf-8")


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def catalog(data):
    for name, expected in PINNED.items():
        require(sha(data/name)==expected, "not frozen v1.1: "+name)
    videos = {v["video_id"]:v for v in jsonl(data/"videos.jsonl")}
    events = {e["event_id"]:e for e in jsonl(data/"atomic_events.jsonl")}
    taxonomy = read(data/"taxonomy.json")
    require(len(videos)==105 and len(events)==25022, "catalog size mismatch")
    return videos, events, taxonomy


def source_check(binding, videos, match_id):
    vid = binding["video_id"]
    require(vid in videos and videos[vid]["match_id"]==match_id, "source/match mismatch")
    require(binding.get("native_video_id") and binding.get("identity_provenance"),
            "explicit native source identity provenance required")
    digest = binding.get("source_sha256")
    require(isinstance(digest,str) and len(digest)==64 and all(c in "0123456789abcdef" for c in digest),
            "source SHA256 required")
    require(binding.get("timeline")=="source_video_media_seconds", "source-local timeline required")
    return videos[vid]


def label_for(task, native, taxonomy, reviewed):
    if task=="story":
        pair = STORY_LABELS.get(native["template_id"])
    else:
        cat, sub = native["native_category"], native["native_subtype"]
        # Existing Chinese public labels can be exported unchanged.
        pair = (cat, sub) if sub in taxonomy["causal"].get(cat,[]) else (
            reviewed.get((CAT_ALIAS.get(cat,cat), sub)) or CAUSAL_LABELS.get((CAT_ALIAS.get(cat,cat),sub)))
    if pair and pair[1] in taxonomy[task].get(pair[0],[]):
        return pair
    return None


def story_rows(doc, template_id, candidate_id):
    if isinstance(doc,dict):
        require(isinstance(doc.get("edl"),list),"explicit EDL list required")
        doc = doc["edl"]
    require(isinstance(doc,list),"EDL must be list or object with edl list")
    return [{"template_id":template_id,"candidate_id":candidate_id,
             "native_segments":doc}]


def causal_rows(doc, stage):
    key = "chains" if stage=="strip831" else "causal_chains"
    require(isinstance(doc,dict) and isinstance(doc.get(key),list),"prediction chains missing")
    if stage=="strip831":
        require(doc.get("schema")=="v2_upstream_strip_json_v1","not frozen strip prediction format")
    else:
        require(doc.get("v3_adapter",{}).get("human_causal_structure_used") is False,
                "adapted prediction provenance missing")
    rows=[]
    for i,c in enumerate(doc[key]):
        ids = c.get("event_ids") if stage=="strip831" else [e.get("event_id") for e in c.get("events",[])]
        rows.append({"candidate_id":c.get("clip_id") if stage=="strip831" else c.get("annotation_id"),
                     "native_category":c.get("chain_category"),
                     "native_subtype":c.get("template_id") if stage=="strip831" else c.get("causal_chain_subtype"),
                     "native_segments":[{"media_in":c["t0_ms"]/1000 if finite(c.get("t0_ms")) else None,
                                         "media_out":c["t1_ms"]/1000 if finite(c.get("t1_ms")) else None,
                                         "event_ids":ids}],
                     "native_chain":c})
    return rows


def segment_projection(s, binding, video, events):
    # Source-less bridge rows are legal only because the caller explicitly
    # binds this entire artifact to a single verified original source.
    vid = binding["video_id"]
    src = s.get("video_id")
    issues=[]
    if src is not None and src not in {binding["native_video_id"],vid}:
        issues.append({"reason":"FOREIGN_SOURCE","native_video_id":src})
    lo,hi=s.get("media_in"),s.get("media_out")
    if not (finite(lo) and finite(hi) and 0<=lo<hi<=video["duration_sec"]):
        issues.append({"reason":"INVALID_SOURCE_INTERVAL","interval":[lo,hi]})
    ids=s.get("event_ids")
    mapped=[]
    if not isinstance(ids,list) or not ids:
        issues.append({"reason":"EMPTY_OR_INVALID_EVENT_IDS"})
        ids=[]
    for eid in ids:
        if not isinstance(eid,str) or not eid:
            issues.append({"reason":"INVALID_EVENT_ID","event_id":eid})
            continue
        candidate=eid if eid.startswith(vid+":E:") else vid+":E:"+eid
        event=events.get(candidate)
        if not event or event["video_id"]!=vid:
            issues.append({"reason":"UNMAPPED_NATIVE_EVENT","event_id":eid})
        elif not (finite(lo) and finite(hi) and min(hi,event["end_sec"])>max(lo,event["start_sec"])):
            issues.append({"reason":"EVENT_OUTSIDE_PREDICTED_WINDOW","event_id":eid})
        else:
            mapped.append(candidate)
    if not mapped:
        issues.append({"reason":"NO_EVAL_EVENT_IDS"})
    return {"video_id":vid,"start_sec":lo,"end_sec":hi,"event_ids":mapped},issues


def project(native, task, binding, video, events, taxonomy, reviewed):
    issues=[]
    pair=label_for(task,native,taxonomy,reviewed)
    if not pair:
        issues.append({"reason":"UNMAPPED_TAXONOMY","native_type":native.get("template_id") or native.get("native_subtype")})
    ss=[]
    excluded=[]
    for i,s in enumerate(native["native_segments"]):
        # Explicitly inactive edits are not part of the actual cut. Keep
        # their original rows in the native archive and record the omission.
        if s.get("include_in_cut") is False:
            excluded.append({"index":i,"reason":"EXPLICITLY_INACTIVE"})
            continue
        # Generated titles with no source footage are not selected video
        # segments. Never silently discard a timed scoreboard/replay row.
        if s.get("shot_kind") in {"title_card","background_card"} and s.get("media_in") is None and s.get("media_out") is None:
            excluded.append({"index":i,"reason":"NON_SOURCE_TITLE_CARD"})
            continue
        row,problems=segment_projection(s,binding,video,events)
        ss.append(row)
        issues.extend({"segment_index":i,**p} for p in problems)
    if not ss:
        issues.append({"reason":"EMPTY_PREDICTED_STORY_OR_CHAIN"})
    if task=="causal" and not video.get("causal_eval_source"):
        issues.append({"reason":"NON_SCORING_CAUSAL_SOURCE"})
    result={"match_id":video["match_id"],"category":pair[0] if pair else None,
            "subtype":pair[1] if pair else None}
    if task=="story":
        result["segments"]=ss
    elif len(ss)==1:
        result.update(ss[0])
    else:
        issues.append({"reason":"INVALID_CAUSAL_SEGMENT_COUNT"})
    return result,issues,excluded


def run(spec, data, out):
    videos,events,taxonomy=catalog(data)
    require(spec.get("schema")=="sportscausal_prediction_export_v1","invalid spec schema")
    require(spec.get("run_id") and spec.get("algorithm_commit") and spec.get("input_tier"),
            "run/algorithm/input provenance required")
    require(isinstance(spec.get("artifacts"),list) and spec["artifacts"],"artifact list required")
    video=source_check(spec["source"],videos,spec["match_id"])
    reviewed={}
    for row in spec.get("reviewed_causal_mapping",[]):
        require(row.get("provenance"),"reviewed mapping provenance required")
        k=(row["native_category"],row["native_subtype"])
        require(k not in reviewed,"duplicate reviewed mapping")
        reviewed[k]=(row["category"],row["subtype"])
    out.mkdir(parents=True,exist_ok=False)
    groups={}
    native_dir=out/"native"
    native_dir.mkdir()
    files=[]
    for i,item in enumerate(spec["artifacts"]):
        stage=item["stage"]
        require(stage in STAGES,"invalid stage")
        task="causal" if stage in {"strip831","adapted_causal"} else "story"
        path=Path(item["path"])
        digest=sha(path)
        require(digest==item["sha256"],"prediction artifact changed: "+str(path))
        saved=native_dir/f"{i:03d}.json"
        saved.write_bytes(path.read_bytes())
        require(sha(saved)==digest,"copy hash mismatch")
        doc=read(saved)
        rows=causal_rows(doc,stage) if task=="causal" else story_rows(doc,item["template_id"],item["candidate_id"])
        # A version/cohort is a distinct prediction setting; never combine
        # historical variants as if they were separate predicted stories.
        variant=item["variant"]
        require(isinstance(variant,str) and variant and all(c.isascii() and (c.isalnum() or c in "_-") for c in variant),"invalid variant")
        key=(task,stage,variant)
        g=groups.setdefault(key,{"predictions":[],"audit":[],"ids":set()})
        for n in rows:
            cid=n["candidate_id"]
            require(isinstance(cid,str) and cid and cid not in g["ids"],"missing/duplicate candidate identity")
            g["ids"].add(cid)
            projected,issues,excluded=project(n,task,spec["source"],video,events,taxonomy,reviewed)
            g["predictions"].append(projected)
            g["audit"].append({"candidate_id":cid,"artifact":str(saved.relative_to(out)),
                "issues":issues,"excluded_non_source_or_inactive":excluded,
                "native":n,"projected":projected})
        files.append({**item,"original_path":str(path),"archived_path":str(saved.relative_to(out)),
                      "sha256":digest,"n_predictions":len(rows)})
    result={"schema":"sportscausal_prediction_export_result_v1","benchmark_ref":BENCHMARK_REF,
            "evaluator_ref":EVAL_REF,"run_metadata":{k:v for k,v in spec.items() if k!="artifacts"},
            "artifacts":files,"groups":[],"http_calls":0,"metrics_computed":False,
            "warning":"Projection readiness is format validity only, not benchmark eligibility or story quality."}
    for (task,stage,variant),g in groups.items():
        stem=f"{task}__{stage}__{variant}"
        bad=sum(bool(row["issues"]) for row in g["audit"])
        write_lines(out/(stem+".audit.jsonl"),g["audit"])
        # Retain every prediction, including unprojectable rows. A partial
        # projection cannot be mistaken for a complete scoring input.
        write_lines(out/(stem+".projected_diagnostic.jsonl"),g["predictions"])
        strict=None
        if not bad:
            strict=stem+".strict.jsonl"
            write_lines(out/strict,g["predictions"])
        result["groups"].append({"task":task,"stage":stage,"variant":variant,
              "n_predictions":len(g["predictions"]),"n_blocked_predictions":bad,
              "strict_path":strict,"status":"BLOCKED_MAPPING" if bad else "FORMAT_READY",
              "audit_path":stem+".audit.jsonl"})
    write(out/"export_manifest.json",result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--spec",type=Path,required=True)
    p.add_argument("--benchmark-dir",type=Path,required=True)
    p.add_argument("--out-dir",type=Path,required=True)
    a=p.parse_args()
    result=run(read(a.spec),a.benchmark_dir,a.out_dir)
    print(json.dumps(result["groups"],ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
