"""R3 combined compiler over frozen A/B artifacts.

Historical V3-R EDLs are preserved byte-for-byte as independent seeds.
An explicit source/candidate mapping and existing file hash are required;
no inferred mapping from a filename, and no historical render or recompute.
"""
import argparse
import hashlib
import json
from pathlib import Path
from copy import deepcopy
from template_graph import read,write,check,number
from story_graph_compiler import compile_story
from story_materializer import materialize

R2A_RESULTS={"keeper_rescue":"repeat","alternating_threats":"alternate",
             "alternating_threats_score_context":"mixed_role_hypothesis"}

def load_seed_manifest(path):
    if path is None:
        return {}
    p=Path(path)
    doc=read(p)
    check(doc.get("schema")=="sportscausal_legacy_seed_manifest_v1","invalid seed manifest")
    result={}
    for row in doc["seeds"]:
        sid=row["story_id"]
        check(sid not in result,"duplicate legacy seed story")
        source=(p.parent/row["path"]).resolve()
        data=source.read_bytes()
        check(hashlib.sha256(data).hexdigest()==row["sha256"],"legacy seed hash mismatch")
        payload=json.loads(data)
        # Accept native list or a named EDL list inside the native object.
        # A manifest must explicitly name that key; never guess the EDL.
        key=row.get("edl_key")
        if key is None:
            segments=payload
        else:
            check(isinstance(payload,dict) and key in payload,"legacy EDL key absent")
            segments=payload[key]
        check(isinstance(segments,list) and bool(segments),"legacy EDL list required")
        result[sid]={"manifest":deepcopy(row),"data":data,"segments":segments}
    return result

def seed_metadata(story,evidence,seed):
    row=seed["manifest"]
    check(story["template_id"]=="comeback" and row["story_id"]==story["story_id"]
          and row["video_id"]==evidence["video_id"] and row["subjects"]==story["subjects"],
          "legacy source/protagonist mismatch")
    check(bool(row.get("source_provenance")),"legacy source provenance required")
    # Preserve the native file; only inspect time fields explicitly named
    # in the manifest. Do not reinterpret legacy verification statuses.
    fields=row.get("time_fields",["media_in","media_out"])
    check(isinstance(fields,list) and len(fields)==2 and all(isinstance(k,str) for k in fields),
          "invalid legacy time field mapping")
    windows=[]
    for seg in seed["segments"]:
        lo,hi=seg.get(fields[0]),seg.get(fields[1])
        check(number(lo) and number(hi) and 0<=lo<hi<=evidence["duration_sec"],
              "legacy segment outside source")
        if seg.get("video_id") is not None:
            check(seg["video_id"]==evidence["video_id"],"legacy segment source mismatch")
        windows.append([lo,hi])
    ordered=all(a[1]<=b[0] for a,b in zip(windows,windows[1:]))
    return {"status":"preserved_legacy_seed","file":"legacy_seed.json",
            "source_provenance":row["source_provenance"],"sha256":row["sha256"],
            "n_segments":len(windows),"duration_sec":sum(b-a for a,b in windows),
            "chronological_nonoverlap":ordered,"source_mapping_basis":"explicit_manifest",
            "use_policy":"independent_agent_seed_pending_comparison_and_video_review",
            "first_live_verified":False,"release_authorized":False}

def compile_pack(evidence,r2a_results,r2bc,*,legacy=None):
    check(r2bc["schema"]=="sportscausal_r2bc_preflight_v1"
          and r2bc["video_id"]==evidence["video_id"] and r2bc["input_tier"]==evidence["input_tier"],
          "frozen R2bc source mismatch")
    tasks=r2bc["observation_tasks"]
    index={t["task_id"]:t for t in tasks}
    check(len(index)==len(tasks) and all(t["video_id"]==evidence["video_id"] for t in tasks),
          "task source/identity mismatch")
    results=[]
    for tid,op in R2A_RESULTS.items():
        r=r2a_results[tid]
        check(r["template_id"]==tid,"wrong R2a template")
        results.append((r,op))
    for tid,r in r2bc["results"].items():
        check(r["template"]["template_id"]==tid,"wrong R2bc template")
        results.append((r,r["operator"]))
    stories={}; counts={}
    for r,op in results:
        check(r["video_id"]==evidence["video_id"] and r["input_tier"]==evidence["input_tier"],
              "candidate source mismatch")
        tid=(r.get("template") or r)["template_id"]
        counts[tid]=len(r["candidates"])
        for c in r["candidates"]:
            sid=c["candidate_id"]
            check(sid.startswith(tid+":") and sid not in stories,"duplicate or mismatched story ID")
            g=compile_story(r,c,op,index)
            b=materialize(g,evidence,index)
            b["story_graph"]["draft_policy"]="anchor_first_not_narrative_complete"
            if tid=="comeback":
                seed=(legacy or {}).get(sid)
                b["legacy_seed"]=seed_metadata(g,evidence,seed) if seed else {
                    "status":"legacy_seed_not_supplied","use_policy":"anchor_only_comparison_not_legacy_replacement"}
            else:
                b["legacy_seed"]={"status":"not_applicable"}
            b["story_graph"]["legacy_seed"]=deepcopy(b["legacy_seed"])
            b["story_graph"]["agent_seed"]={"file":"legacy_seed.json" if b["legacy_seed"]["status"]=="preserved_legacy_seed" else "initial_edl.json",
                "status":"comparison_pending" if b["legacy_seed"]["status"]=="preserved_legacy_seed" else "anchor_preview",
                "first_live_verified":False,"release_authorized":False}
            stories[sid]=b
    check(set(legacy or {})<=set(stories),"unmatched legacy seed")
    return {"schema":"sportscausal_r3_pack_v1","video_id":evidence["video_id"],
            "input_tier":evidence["input_tier"],"stories":stories,"template_counts":counts,
            "observation_tasks":deepcopy(tasks),"http_calls":0,"quality_verified":False,
            "first_live_verified":False,"release_authorized":False}

def write_pack(out,pack,legacy):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    summary={"video_id":pack["video_id"],"input_tier":pack["input_tier"],
             "template_counts":pack["template_counts"],"stories":[],
             "n_global_observation_tasks":len(pack["observation_tasks"]),
             "http_calls":0,"quality_verified":False,"first_live_verified":False,
             "release_authorized":False}
    for sid,b in pack["stories"].items():
        folder=sid.replace(":","__")
        check(folder and all(c.isascii() and (c.isalnum() or c in "_-") for c in folder),
              "invalid story directory")
        d=out/folder
        d.mkdir()
        for name in ("story_graph","materials","initial_edl","context_pool","observation_tasks","story_diagnostics","legacy_seed"):
            write(d/(name+".json" if name!="legacy_seed" else "legacy_seed_metadata.json"),b[name])
        if sid in legacy:
            (d/"legacy_seed.json").write_bytes(legacy[sid]["data"])
        g=b["story_graph"]; diag=b["story_diagnostics"]
        summary["stories"].append({"story_id":sid,"template_id":g["template_id"],
            "operator":g["operator"],"subjects":g["subjects"],
            "n_segments":diag["n_segments"],"duration_sec":diag["duration_sec"],
            "missing_required_nodes":diag["missing_required_nodes"],
            "structurally_complete":diag["structurally_complete"],
            "n_context_candidates":diag["n_context_candidates"],
            "n_observation_tasks":len(b["observation_tasks"]),
            "strict_threat_metric_eligible":g["strict_threat_metric_eligible"],
            "legacy_seed":b["legacy_seed"],"agent_seed":g["agent_seed"],"folder":folder})
    write(out/"summary.json",summary)
    write(out/"observation_tasks.json",{"video_id":pack["video_id"],"tasks":pack["observation_tasks"]})

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("evidence","r2a4-dir","r2bc-dir","out-dir"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--legacy-seed-manifest")
    p.add_argument("--allow-dev",action="store_true")
    a=p.parse_args()
    e=read(a.evidence)
    check(a.allow_dev or e["input_tier"] in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development input requires --allow-dev")
    r2a={tid:read(Path(a.r2a4_dir)/(tid+".json")) for tid in R2A_RESULTS}
    r2bc=read(Path(a.r2bc_dir)/"anchor_pack.json")
    legacy=load_seed_manifest(a.legacy_seed_manifest)
    pack=compile_pack(e,r2a,r2bc,legacy=legacy)
    write_pack(a.out_dir,pack,legacy)

if __name__=="__main__":
    main()
