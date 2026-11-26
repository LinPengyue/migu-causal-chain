"""Stage an isolated copy of the original algo with minimal opt-in input hooks.

The delivery tree is never modified. P1/P2/P3, outer loop, timeline and
Verifier modules remain byte-identical. Only two existing files are patched
at exact known source locations (Critic/Planner inputs, existing protection
policy); the original execution entry and decisions are retained.
"""
import argparse
import ast
import hashlib
from pathlib import Path
import shutil
from template_graph import check, write

PINNED={
    "story_e2e_agent.py":"6c69e861507b82e9a9c766fc1d99437759472971",
    "story_paid_eval.py":"0f86b3f625f51a8ec362e80b0f9e2c23a7a62c7b",
    "story_first_search.py":"c083180a8b78d5f9c4966d079a2ae70178674b6a",
    "story_first_hypotheses.py":"d97676be6fc58e81396498cdefb1c959943a1b47",
    "story_first_revision.py":"0abb25001d5f5a063512481a27d56ebb374ba5af",
    "story_first_video_review.py":"2eb9360e0da66b2fb8b6e64181743f656b7c56b6",
    "story_first_p3.py":"f97e486f4515f0bcb53771b97e27073150e93726",
    "story_first_outer.py":"95e52472f9b34c047569c9aba0bb7ab7836227ce",
    "story_video_verifier.py":"a7d958785bc4a7ba307f71650f407ba4db41d5fd",
    "dual_video_vision_verifier.py":"d873ea8e2495382a13a44d26b574f3b7b587fb23",
    "story_timeline.py":"58871914da304caf3b26f750005e5be5a453e6aa",
}
PATCHED={"story_e2e_agent.py","story_paid_eval.py"}

def blob(b):
    return hashlib.sha1(("blob %d\0"%len(b)).encode()+b).hexdigest()

def replace_once(s,old,new):
    check(s.count(old)==1,"original source hook mismatch: "+old[:100])
    return s.replace(old,new,1)

def patch_entry(s):
    s=replace_once(s,
        "        # P10-B: rederive an inference-only, source/EDL-bound narrative graph.",
        "        from .r3_critic_adapter import scope_diagnosis, planner_view, protect_planner_intents\n"
        "        diag = scope_diagnosis(diag, plan, working_edl)\n"
        "        # P10-B: rederive an inference-only, source/EDL-bound narrative graph.")
    s=replace_once(s,
        "                    observations=obs,\n                    diagnosis=diag,\n                    audit_dir=round_dir / \"paid_api\",\n                    extra_frames=extra_frames or None,",
        "                    observations=obs,\n                    diagnosis=planner_view(diag),\n                    audit_dir=round_dir / \"paid_api\",\n                    extra_frames=extra_frames or None,")
    s=replace_once(s,
        "        rev = plan_from_diagnosis(\n            diag,",
        "        planner_diag = planner_view(diag)\n        rev = plan_from_diagnosis(\n            planner_diag,")
    s=replace_once(s,
        "                        diagnosis=diag,\n                        vlm_critic=vlm_critic or {},\n                        protected_goal_ids=list(diag.get(\"protected_goal_segment_ids\") or []),",
        "                        diagnosis=planner_diag,\n                        vlm_critic=vlm_critic or {},\n                        protected_goal_ids=list(planner_diag.get(\"protected_goal_segment_ids\") or []),")
    s=replace_once(s,
        "        if story_first_proposals:\n            selection = llm_rev.get(\"story_first_trial\")",
        "        if \"r3_story_context\" in diag:\n"
        "            from .story_revision_planner import _protect_filter\n"
        "            rev = protect_planner_intents(rev, diag, _protect_filter)\n"
        "        if story_first_proposals:\n            selection = llm_rev.get(\"story_first_trial\")")
    return s

def patch_paid(s):
    # Only Critic and Planner prompts; no shared SYSTEM_VERIFIER or
    # verifier function changes. Absent explicit R3 context = old prompt.
    s=replace_once(s,
        '    mock = {"semantic_evidence": [], "keep_story_if_no_defect": True, "confidence": 0}',
        '    if diagnosis.get("r3_story_context"):\n'
        '        prompt += "\\nEvaluate the specified story goal and required nodes, not a default comeback. "\n'
        '        prompt += "Required nodes are hypotheses, not certified visual facts. "\n'
        '        prompt += "R3_STORY_CONTEXT:" + json.dumps(diagnosis["r3_story_context"], ensure_ascii=False)\n'
        '        prompt += "\\nPROTECTED_STORY_SEGMENTS:" + json.dumps(diagnosis.get("protected_story_segment_ids", []))\n'
        '    mock = {"semantic_evidence": [], "keep_story_if_no_defect": True, "confidence": 0}')
    s=replace_once(s,
        '    user = (\n        "Given diagnosis + VLM critic summary, propose a story revision plan.\\n"',
        '    if diagnosis.get("r3_story_context"):\n'
        '        payload["r3_story_context"] = diagnosis["r3_story_context"]\n'
        '        payload["protected_story_segment_ids"] = diagnosis.get("protected_story_segment_ids", [])\n'
        '    user = (\n        "Given diagnosis + VLM critic summary, propose a story revision plan.\\n"')
    return s

def function_ast(s):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(s).body
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}

def stage(algo_dir,out):
    source=Path(algo_dir).resolve()
    out=Path(out).resolve()
    check(source!=out and source not in out.parents,"stage must be outside original algo")
    check(not out.exists(),"fresh stage directory required")
    package=source/"story_video_agent_v3"
    before={f:blob((package/f).read_bytes()) for f in PINNED}
    check(before==PINNED,"original pinned source mismatch")
    # Compile patches and verify paid evaluator changes are limited to
    # exactly the two intended functions before copying anything.
    originals={f:(package/f).read_text(encoding="utf-8") for f in PATCHED}
    patched={"story_e2e_agent.py":patch_entry(originals["story_e2e_agent.py"]),
             "story_paid_eval.py":patch_paid(originals["story_paid_eval.py"])}
    for f,s in patched.items():
        compile(s,f,"exec")
    a,b=map(function_ast,(originals["story_paid_eval.py"],patched["story_paid_eval.py"]))
    check(set(a)==set(b) and {k for k in a if a[k]!=b[k]}==
          {"run_vlm_story_critic","run_llm_revision_planner"},"unexpected paid evaluator change")
    shutil.copytree(source,out/"algo",symlinks=True,ignore=shutil.ignore_patterns("__pycache__","*.pyc",".git"))
    staged=out/"algo"/"story_video_agent_v3"
    for f,s in patched.items():
        check(not (staged/f).is_symlink(),"refuse patching symlink")
        (staged/f).write_text(s,encoding="utf-8")
    shutil.copy2(Path(__file__).with_name("r3_critic_adapter.py"),staged/"r3_critic_adapter.py")
    after={f:blob((staged/f).read_bytes()) for f in PINNED}
    check({f for f in before if before[f]!=after[f]}==PATCHED,"unexpected protected module changes")
    check({f:blob((package/f).read_bytes()) for f in PINNED}==before,"original source changed")
    write(out/"overlay_manifest.json",{"original_algo":str(source),"staged_algo":str(out/"algo"),
        "original_blobs":before,"staged_blobs":after,"patched_existing_files":sorted(PATCHED),
        "added_module":"r3_critic_adapter.py","original_tree_unchanged":True,
        "paid_eval_changed_functions":sorted(k for k in a if a[k]!=b[k]),
        "verifier_and_story_first_modules_unchanged":True,"http_calls":0})
    return out/"algo"

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--algo-dir",required=True); p.add_argument("--out-dir",required=True)
    a=p.parse_args(); print(stage(a.algo_dir,a.out_dir))
