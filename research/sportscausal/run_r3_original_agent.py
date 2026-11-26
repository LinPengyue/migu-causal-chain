"""R4/R5.3: real rendering and ORIGINAL run_story_e2e on a frozen R3 seed.

No new Story Agent, no altered Verifier, no fixtures and no rerun of V3-R.
One run can collect the native outer-loop v0/v1/v2/v3 previews. Default is
render-only; explicit paid opt-in uses the original provider/limits.
"""
import argparse
import hashlib
import sys
import time
from pathlib import Path
from template_graph import check, read, write
from r3_legacy_agent_adapter import sha, validate_source_events
from stage_r3_critic_adapter import stage, PINNED, PATCHED, blob

def frozen_input(pack,evidence_path,events_path):
    pack=Path(pack).resolve()
    plan,rows,report=[read(pack/n) for n in
                      ("story_plan.json","candidate_edl.json","report.json")]
    evidence=read(evidence_path)
    events=validate_source_events(evidence,read(events_path))
    hashes=report["input_hashes"]
    def original_hash(filename):
        values=[v for p,v in hashes.items() if Path(p).name==filename]
        check(len(values)==1,"ambiguous frozen source hash: "+filename)
        return values[0]
    check(sha(evidence_path)==original_hash("evidence.json"),"frozen evidence mismatch")
    check(sha(events_path)==original_hash("events_enriched.json"),"frozen events mismatch")
    check(report["video_id"]==evidence["video_id"]==plan["match_id"],"video ID mismatch")
    check(plan["r3_adapter"]["story_id"]==report["story_id"] and
          plan["r3_adapter"]["input_tier"]==evidence["input_tier"],"story/input tier mismatch")
    check(plan["candidate_edl"]==rows==plan["edl"],"plan/EDL mismatch")
    check(plan["a_story_template_context"]["template_id"]==plan["template_id"],
          "inconsistent template context")
    check(rows and all(r.get("preview_only") is True and
                       r.get("first_live_verified") is False for r in rows),
          "expected unverified preview seed")
    return plan,rows,report,evidence,events

def check_overlay(algo_dir,manifest_path):
    algo=Path(algo_dir).resolve()
    m=read(manifest_path)
    check(Path(m["staged_algo"]).resolve()==algo,"overlay path mismatch")
    check(m["original_blobs"]==PINNED and set(m["patched_existing_files"])==PATCHED,
          "overlay pin mismatch")
    for f,expected in m["staged_blobs"].items():
        check(blob((algo/"story_video_agent_v3"/f).read_bytes())==expected,
              "staged module mismatch: "+f)
    check(all(m["staged_blobs"][f]==PINNED[f] for f in PINNED if f not in PATCHED),
          "P1/P2/P3/Outer/Verifier changed")
    check(sha(algo/"story_video_agent_v3"/"r3_critic_adapter.py")==
          sha(Path(__file__).with_name("r3_critic_adapter.py")),"adapter mismatch")
    return m

def outer_summary(audit,root):
    """Read native outputs as research previews, never as quality verdicts."""
    p=root/"story_first_outer"/"story_first_outer_comparison.json"
    if not p.is_file():
        return {"status":"NO_NATIVE_OUTER_COMPARISON","versions":[]}
    doc=read(p)
    versions=[]
    for v in doc["comparison"]:
        edl=read(v["edl"])
        mp4=Path(v["mp4"])
        check(mp4.is_file() and sha(mp4)==v["mp4_sha256"],"outer version MP4 hash mismatch")
        active=[r for r in edl if r.get("include_in_cut",True)]
        versions.append({"outer_rounds":v["outer_rounds"],"status":v["status"],
                         "accepted_preview_changes":v["accepted_changes"],
                         "edl":v["edl"],"mp4":v["mp4"],"mp4_sha256":v["mp4_sha256"],
                         "duration_sec":v["duration_sec"],"segments":len(active),
                         "segment_ids":[r["segment_id"] for r in active],
                         "quality_claim":"not_evaluated_by_this_summary"})
    return {"status":"NATIVE_OUTER_COMPARISON","requested":doc["requested_outer_rounds"],
            "attempted":doc["attempted_outer_rounds"],"selected_preview_changes":doc["accepted_changes"],
            "versions":versions,"native_report":str(p),"native_preview_only":doc["preview_only"]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("pack","evidence","events","match-json","source","source-manifest","original-algo","out-dir"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--allow-dev",action="store_true")
    p.add_argument("--enable-real-api",action="store_true")
    p.add_argument("--approve-budget",action="store_true")
    p.add_argument("--outer-rounds",type=int,choices=(1,2,3),default=3)
    p.add_argument("--max-calls",type=int,default=24)
    p.add_argument("--max-cost-usd",type=float,default=0.10)
    p.add_argument("--enable-native-broadcast-observation",action="store_true")
    p.add_argument("--prepared-dir",help="reuse this runner's exact rendered seed; no repeat render")
    a=p.parse_args()
    check(not a.enable_real_api or (a.approve_budget and 1<=a.max_calls<=24 and
          0<a.max_cost_usd<=0.10),"explicit approved original provider budget required")
    check(not a.enable_native_broadcast_observation or a.enable_real_api,
          "native broadcast opt-in requires real API")
    plan,rows,report,evidence,events=frozen_input(a.pack,a.evidence,a.events)
    check(a.allow_dev or evidence["input_tier"] in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires explicit opt-in")
    source=Path(a.source).resolve()
    source_manifest=read(a.source_manifest)
    check(source_manifest["video_id"]==evidence["video_id"],"source video identity mismatch")
    check(bool(source_manifest.get("provenance")),"source provenance required")
    source_sha=sha(source)
    check(source_sha==source_manifest["sha256"],"source hash mismatch")
    match=Path(a.match_json).resolve()
    check(match.is_file(),"original match JSON missing")
    out=Path(a.out_dir).resolve()
    out.mkdir(parents=True,exist_ok=False)
    algo=stage(a.original_algo,out/"overlay")
    overlay=check_overlay(algo,out/"overlay"/"overlay_manifest.json")
    sys.path.insert(0,str(algo))
    from story_video_agent_v3.story_e2e_agent import StoryE2EInputs,run_story_e2e,_render_edl
    from story_video_agent_v3.story_video_verifier import timeline_mp4_aligned
    from story_video_agent_v3.fresh_e2e_cli import validate_render_rows
    from story_video_agent.media import probe_video
    media=probe_video(source)
    check(abs(float(media.duration_sec)-float(evidence["duration_sec"]))<=2,
          "source duration mismatch")
    check(not any(r.get("is_replay") is True for r in rows),"explicit replay seed row")
    # Frozen seed is already checked against original nonlive events by
    # R4/R5.1. Do not silently trim, reorder, or mark any material first-live.
    rows=validate_render_rows(rows)
    pack=Path(a.pack).resolve()
    provenance={"schema":"sportscausal_original_agent_run_v1",
        "story_id":report["story_id"],"video_id":report["video_id"],
        "input_tier":evidence["input_tier"],"source_sha256":source_sha,
        "source_manifest":source_manifest,"source_manifest_sha256":sha(a.source_manifest),
        "evidence_sha256":sha(a.evidence),"events_sha256":sha(a.events),
        "match_json_sha256":sha(match),"plan_sha256":sha(pack/"story_plan.json"),
        "edl_sha256":sha(pack/"candidate_edl.json"),
        "original_algorithm":"run_story_e2e","fresh_v3r":False,
        "legacy_single_loop":False,"research_preview_only":True}
    write(out/"input_provenance.json",provenance)
    write(out/"story_plan.json",plan)
    write(out/"candidate_edl.json",rows)
    t0=time.time()
    if a.prepared_dir:
        prepared=Path(a.prepared_dir).resolve()
        old=read(prepared/"input_provenance.json")
        for k in ("story_id","video_id","source_sha256","evidence_sha256","events_sha256",
                  "match_json_sha256","plan_sha256","edl_sha256"):
            check(old[k]==provenance[k],"prepared seed differs: "+k)
        seed=read(prepared/"render_manifest.json")
        initial=Path(seed["story_clean"])
        check(sha(initial)==seed["story_clean_sha256"],"prepared MP4 hash mismatch")
        render={"ok":True,"story_clean":str(initial),"reused_prepared_seed":str(prepared)}
    else:
        render=_render_edl(plan=plan,video=source,edl=rows,out_dir=out/"initial_render")
        check(render["ok"] and render["story_clean"],"original renderer failed")
        initial=Path(render["story_clean"])
    alignment=timeline_mp4_aligned(edl=rows,mp4=initial)
    check(alignment["aligned"],"original initial render and EDL not aligned")
    write(out/"render_manifest.json",{**render,"story_clean_sha256":sha(initial),
         "alignment":alignment,"elapsed_sec":round(time.time()-t0,3),
         "first_live_verified":False,"release_authorized":False})
    if not a.enable_real_api:
        write(out/"report.json",{**provenance,"status":"RENDERED_ONLY","http_calls":0,
             "initial_mp4":str(initial),"actual_duration_sec":alignment["mp4_duration_sec"],
             "quality_verified":False})
        return
    # Original main entry. max_rounds=1 is the formal main loop's existing
    # paid protocol; story_first_outer_rounds is the separate story expansion
    # loop count. Never confuse these knobs or run 3 independent paid jobs.
    run_dir=out/"original_agent"
    inp=StoryE2EInputs(match_json=match,source_mp4=source,out_dir=run_dir,
        baseline_edl=out/"candidate_edl.json",story_plan=out/"story_plan.json",
        initial_story_mp4=initial,events_json=Path(a.events).resolve(),
        match_id=evidence["video_id"],algo_root=algo,run_fresh_v3r=False,
        skip_vlm=False,enable_real_api=True,i_approve_budget=True,
        enable_story_first=True,story_first_outer_rounds=a.outer_rounds,
        enable_native_broadcast_observation=a.enable_native_broadcast_observation,
        smoke_render=False,force_render_initial=False,force_render_candidate=False,
        max_rounds=1,max_calls=a.max_calls,max_cost_usd=a.max_cost_usd,max_retries=0)
    audit=run_story_e2e(inp)
    # Preserve native output and decisions, with actual provenance and
    # separate preview comparison. Never reclassify ACCEPTED_PREVIEW as
    # quality improvement, or replace formal delivery with a research cut.
    write(out/"report.json",{**provenance,"status":"ORIGINAL_AGENT_RETURNED",
        "original_audit":str(run_dir/"story_e2e_audit.json"),"original_ok":audit.get("ok"),
        "original_error":audit.get("error"),"http_calls":audit.get("http_calls"),
        "est_cost_usd":audit.get("est_cost_usd"),"native_delivery":audit.get("delivery"),
        "native_status_gates":audit.get("status_gates"),"outer":outer_summary(audit,run_dir),
        "elapsed_sec":round(time.time()-t0,3),"quality_verified_by_runner":False})

if __name__=="__main__":
    main()
