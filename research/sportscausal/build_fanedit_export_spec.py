"""Build a post-inference export spec from a fresh general run and optional
native Agent runs. No inference, no evaluator, no reference story read.
Caller supplies verified FanEdit/native source identity; archive every R3
candidate and every actual Agent version, not only a successful story.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from export_fanedit_predictions import read, write, require, sha

def artifact(path, stage, variant, expected=None, **kw):
    path=Path(path).resolve(strict=True)
    actual=sha(path)
    require(expected is None or expected==actual,"artifact hash differs: "+str(path))
    return {"path":str(path),"sha256":actual,"stage":stage,"variant":variant,**kw}

def build(fresh, binding, agent_dirs, run_id):
    fresh=Path(fresh).resolve(strict=True)
    m=read(fresh/"run_manifest.json")
    require(m["status"]=="COMPLETE","fresh V3-R run incomplete")
    require(binding["native_video_id"]==m["video_id"] and
            binding["source_sha256"]==m["inputs"]["source_mp4"]["sha256"],
            "fresh source identity mismatch")
    require(binding.get("identity_provenance"),"source matching evidence required")
    expected=m["artifacts"]
    def from_fresh(p,stage,variant,**kw):
        return artifact(fresh/p,stage,variant,expected[p],**kw)
    summary_path="08_r3/summary.json"
    require(sha(fresh/summary_path)==expected[summary_path],"R3 summary changed")
    summary=read(fresh/summary_path)
    require(summary["video_id"]==m["video_id"] and summary["input_tier"]==m["input_tier"],
            "R3 summary identity mismatch")
    artifacts=[from_fresh("02_strip831/strip_A_original.json","strip831","all"),
               from_fresh("03_v1_adapt/predicted_causal.json","adapted_causal","all")]
    excluded_hypotheses=[]
    candidates={}
    for row in summary["stories"]:
        tid,cid=row["template_id"],row["story_id"]
        if tid=="alternating_threats_score_context":
            # Retain the native diagnostic separately. It is explicitly NOT
            # an evaluated ninth subtype and must not masquerade as strict alternation.
            excluded_hypotheses.append(from_fresh("08_r3/"+row["folder"]+"/initial_edl.json",
                "r3_initial","mixed_diagnostic",template_id=tid,candidate_id=cid))
            continue
        require(cid not in candidates,"duplicate R3 candidate")
        candidates[cid]=tid
        artifacts.append(from_fresh("08_r3/"+row["folder"]+"/initial_edl.json",
            "r3_initial","all",template_id=tid,candidate_id=cid))
    seen=set()
    runs=[]
    for folder in agent_dirs:
        d=Path(folder).resolve(strict=True)
        p=read(d/"input_provenance.json")
        r=read(d/"report.json")
        cid=p["story_id"]
        require(cid in candidates and cid not in seen,"Agent run unknown or duplicate candidate")
        seen.add(cid)
        require(p["video_id"]==m["video_id"] and p["source_sha256"]==binding["source_sha256"]
                and p["input_tier"]==m["input_tier"],"Agent source/tier mismatch")
        require(p["evidence_sha256"]==expected["04_evidence/evidence.json"]
                and p["events_sha256"]==expected["01_enrich/events_enriched.json"]
                and p["match_json_sha256"]==m["inputs"]["match_json"]["sha256"],
                "Agent inputs differ from fresh run")
        # The runner hashes the input critic pack, then serializes its validated
        # EDL to candidate_edl.json. Keep both digests; byte equality is not
        # assumed across that normalization boundary.
        seed_sha = sha(d/"candidate_edl.json")
        args={"template_id":candidates[cid],"candidate_id":cid}
        artifacts.append(artifact(d/"candidate_edl.json","agent_v0","all",**args))
        native=d/"original_agent"
        final=native/"99_final/final_edl.json"
        audit_path=native/"story_e2e_audit.json"
        outer=native/"story_first_outer/story_first_outer_comparison.json"
        meta={"candidate_id":cid,"runner_report":str(d/"report.json"),
              "runner_report_sha256":sha(d/"report.json"),"input_provenance_sha256":sha(d/"input_provenance.json"),
              "input_pack_edl_sha256":p["edl_sha256"],"serialized_seed_edl_sha256":seed_sha,
              "runner_status":r.get("status"),"http_calls":r.get("http_calls"),
              "estimated_cost_usd":r.get("est_cost_usd"),"runner_elapsed_sec":r.get("elapsed_sec"),
              "native_final_present":final.is_file(),"native_delivery_status":None}
        if audit_path.is_file():
            a=read(audit_path)
            meta.update(native_audit=str(audit_path),native_audit_sha256=sha(audit_path),
                native_delivery_status=a.get("delivery",{}).get("delivery_status"),
                native_delivery=a.get("delivery",{}).get("release_authorized"),
                native_agent_elapsed_sec=a.get("elapsed_sec"))
        if final.is_file():
            require(audit_path.is_file(),"final EDL without native audit")
            artifacts.append(artifact(final,"agent_native_final","all",**args))
        if outer.is_file():
            c=read(outer)
            meta["outer_comparison_sha256"]=sha(outer)
            meta["outer_versions"]=c["comparison"]
            for version in c["comparison"]:
                n=version["outer_rounds"]
                if n==0:
                    continue
                # Only read the actual native version path. Absolute paths
                # from a moved archive must be explicitly restored, not guessed.
                artifacts.append(artifact(version["edl"],"agent_preview","v"+str(n),**args))
        runs.append(meta)
    return {"schema":"sportscausal_prediction_export_v1","run_id":run_id,
        "algorithm_commit":m["git_head"],"input_tier":m["input_tier"],
        "match_id":binding["match_id"],"source":binding,
        "fresh_manifest":str(fresh/"run_manifest.json"),"fresh_manifest_sha256":sha(fresh/"run_manifest.json"),
        "input_hashes":m["inputs"],"r3_template_counts":summary["template_counts"],
        "n_r3_predictions":len(candidates),"n_agent_attempts":len(runs),
        "agent_coverage_complete":set(candidates)==seen,
        "unattempted_candidate_ids":sorted(set(candidates)-seen),
        "agent_runs":runs,"mixed_diagnostic_artifacts":excluded_hypotheses,
        "scope":"template-conditioned development if known reference type selected; do not treat missing runs as complete batch",
        "artifacts":artifacts}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fresh-dir",type=Path,required=True)
    p.add_argument("--source-binding",type=Path,required=True)
    p.add_argument("--agent-dir",type=Path,action="append",default=[])
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    require(not a.out.exists(),"export spec exists")
    spec=build(a.fresh_dir,read(a.source_binding),a.agent_dir,a.run_id)
    write(a.out,spec)
    print("R3 candidates:",spec["n_r3_predictions"],"Agent attempts:",spec["n_agent_attempts"])


if __name__=="__main__":
    main()
