#!/usr/bin/env python3
"""Export short FIRST-LIVE-UNVERIFIED pre-turn video observation probes.

Reads V3-A's proactive search output; NEVER edits EDL or signs first-live.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for b in iter(lambda:fh.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def encode(source: Path, a: float, b: float, output: Path):
    if b-a < 2.0 or a < 0: return {"ok": False, "reason": "bad_duration"}
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y",
         "-ss",f"{a:.3f}","-i",str(source),"-t",f"{b-a:.3f}",
         "-map","0:v:0","-map","0:a?","-vf","scale=960:-2",
         "-c:v","libx264","-preset","veryfast","-crf","25",
         "-c:a","aac","-b:a","96k","-movflags","+faststart",str(output)]
    r=subprocess.run(cmd, capture_output=True,text=True)
    ok=(r.returncode==0 and output.is_file() and output.stat().st_size>1024)
    return {"ok":ok,"path":str(output) if ok else None,
            "error":r.stderr[-700:] if not ok else None}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--run-dir",required=True,type=Path)
    p.add_argument("--source-mp4",required=True,type=Path)
    p.add_argument("--out-dir",required=True,type=Path)
    p.add_argument("--top-k",type=int,default=4)
    args=p.parse_args()
    if not 1<=args.top_k<=6:p.error("top-k must be 1..6")
    if args.out_dir.exists():raise FileExistsError(args.out_dir)
    report_path=args.run_dir/"02_round_01/proactive_turn_context_search.json"
    audit_path=args.run_dir/"story_e2e_audit.json"
    report=json.loads(report_path.read_text())
    audit=json.loads(audit_path.read_text())
    source_sha=digest(args.source_mp4)
    if source_sha!=audit.get("source_sha256"):
        raise ValueError("source SHA mismatch with main V3-A run")
    if report.get("mode")!="OBSERVATION_ONLY":
        raise ValueError("not observation-only report")
    args.out_dir.mkdir(parents=True)
    exported=[]
    for i,target in enumerate(report.get("targets") or [],1):
        probes=target.get("ranked_event_probes") or []
        clips=[]
        for j,c in enumerate(probes[:args.top_k],1):
            a,b=float(c["source_pts_start"]),float(c["source_pts_end"])
            # Short review includes extra +/-2s visual context, bounded by the
            # pre-turn search interval, never overlapping any goal footage.
            low,high=map(float,target["source_search_interval"])
            a=max(low,a-2.0);b=min(high,b+2.0)
            clips.append({
                "candidate":c,
                "review_window":[round(a,3),round(b,3)],
                "video":encode(args.source_mp4,a,b,args.out_dir/f"{i:02d}_event_{j:02d}.mp4")
            })
        if not clips:
            a,b=map(float,target["fallback_observation_interval"])
            clips=[{"candidate":None,"review_window":[a,b],
                    "video":encode(args.source_mp4,a,b,args.out_dir/f"{i:02d}_fallback_observation.mp4")}]
        exported.append({
            "turn_segment_id":target["turn_segment_id"],
            "before_segment_id":target["before_segment_id"],
            "search_interval":target["source_search_interval"],
            "clips":clips,
            "semantic_judgment":"NOT_PERFORMED",
            "first_live_status":"UNRESOLVED",
            "fit_to_story":"NOT_PERFORMED",
        })
    manifest={
        "schema":"v3a_turn_context_review_v1",
        "source_sha256":source_sha,"paid_http":0,"edl_modified":False,
        "first_live_verified":False,"quality_improved":False,
        "source_input_mode":(audit.get("baseline") or {}).get("input_mode"),
        "targets":exported,
        "review_question":"Does this continuous LIVE-original source context provide NEW explanatory game state, pressure, or emotional transition just before the already retained turning-point action? Is it replay/slow motion? Does BEFORE-CANDIDATE-AFTER read naturally?",
        "next_decision":"No insertion until video narrative-fit and first-live proof; proposals are research observations, not finished output.",
    }
    (args.out_dir/"review_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"target_count":len(exported),"probe_count":sum(len(t["clips"]) for t in exported),
                      "out":str(args.out_dir),"paid_http":0,"edl_modified":False},ensure_ascii=False))


if __name__=="__main__":main()
