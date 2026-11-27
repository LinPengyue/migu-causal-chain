"""Exercise original structural Critic/search and actual P1 prompt preparation.

Zero HTTP, no videos decoded or rendered. No full agent loop is executed.
Pass the isolated staged algo from stage_r3_critic_adapter.py.
"""
import argparse
import json
from pathlib import Path
import sys
from template_graph import check, write
from r3_legacy_agent_adapter import load_adapter
from r3_critic_adapter import scope_diagnosis, planner_view

def run(bundle,events,algo_dir,out):
    sys.path.insert(0,str(Path(algo_dir).resolve()))
    from story_video_agent_v3.global_story_critic import structural_diagnosis
    from story_video_agent_v3.story_evidence_search import search_window_for_issue
    from story_video_agent_v3.story_first_hypotheses import (
        adjacent_story_anchor_pairs,prepare_story_input,model_messages,_text)
    from story_video_agent_v3.story_revision_planner import _protect_filter
    from story_video_agent_v3.fresh_e2e_cli import validate_render_rows
    from r3_critic_adapter import protect_planner_intents
    plan,rows=bundle["plan"],bundle["edl"]
    # Run the exact native render validator before a pack is reported ready.
    # This is the existing safety check, not a new gate or renderer change.
    validate_render_rows(rows)
    d=Path(out); d.mkdir(parents=True,exist_ok=False)
    # Confirm the exact legacy serialization, not merely prepared metadata.
    expected=plan["a_story_template_context"]
    prefix='{"a_story_template_context": '
    text=_text(plan,9000)
    check(text.startswith(prefix),"P1 essential context not at prefix")
    actual,_=json.JSONDecoder().raw_decode(text[len(prefix):])
    check(actual==expected,"P1 essential template truncated")
    pairs=adjacent_story_anchor_pairs(rows)
    request=None
    if pairs:
        left,right=pairs[0]
        prepared=prepare_story_input(rows,events,story_plan=plan,
            from_segment_id=left,to_segment_id=right)
        request=model_messages(prepared)
        payload=json.loads(next(x["content"] for x in request if x["role"]=="user"))
        check(payload["frozen_story_plan"]==text,"actual P1 request differs from plan prefix")
        write(d/"fixed_p1_generator_request.json",request)
    original=structural_diagnosis(edl=rows,story_plan=plan,raw_events=events)
    scoped=scope_diagnosis(original,plan,rows)
    planner=planner_view(scoped)
    targets=[{"issue_id":i["issue_id"],"score_before":i.get("score_before"),
              "score_after":i.get("score_after"),"search":search_window_for_issue(i,rows),
              "r3_goal_target":i.get("r3_goal_target")}
             for i in scoped.get("issues",[]) if i.get("category")=="goal_coverage"]
    protected=scoped["protected_story_segment_ids"]
    # Deterministic fixture only: original protection function used on a
    # synthetic non-evidenced removal, not a real planner or quality result.
    old_goals=set(original.get("protected_goal_segment_ids") or [])
    extra=[sid for sid in protected if sid not in old_goals]
    fixture=None
    if extra:
        fixture=protect_planner_intents({"decision":"REVISE","revision_intents":[
            {"intent_id":"fixture_drop","action":"drop","target_segment_id":extra[0]}]},
            scoped,_protect_filter)
        check(fixture["revision_intents"][0]["action"]=="keep","required story anchor protection not inherited")
    write(d/"story_plan.json",plan)
    write(d/"candidate_edl.json",rows)
    write(d/"original_critic_diagnosis.json",original)
    write(d/"scoped_critic_diagnosis.json",scoped)
    write(d/"planner_diagnosis.json",planner)
    write(d/"report.json",{"story_id":bundle["graph"]["story_id"],
        "video_id":bundle["graph"]["video_id"],"template_context_survives_actual_p1_cap":True,
        "native_render_rows_validated":True,
        "p1_request_prepared":request is not None,"n_p1_pairs":len(pairs),
        "original_goal_issues":[i["issue_id"] for i in original.get("issues",[]) if i.get("category")=="goal_coverage"],
        "native_goal_search_targets":targets,"scope_audit":scoped["r3_scope_audit"],
        "protected_story_segment_ids":protected,"original_goal_segment_ids":sorted(old_goals),
        "planner_protection_fixture":fixture,"input_hashes":bundle["input_hashes"],
        "http_calls":0,"video_decoded":False,"quality_verified":False,
        "first_live_verified":False,"release_authorized":False})

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("story-dir","evidence","events","algo-dir","out-dir"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--allow-dev",action="store_true")
    a=p.parse_args()
    bundle,events=load_adapter(a.story_dir,a.evidence,a.events)
    check(a.allow_dev or bundle["graph"]["input_tier"] in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires explicit opt-in")
    run(bundle,events,a.algo_dir,a.out_dir)
