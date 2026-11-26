"""R4/R5.2: scoped inputs for the ORIGINAL Critic/Planner.

Only opt-in R3 plans carry agent_story_context. No alternate loop, no
Verifier changes, no new recovery/observation algorithm. The existing
scoreboard detector and native search still decide the action search prior.
"""
from copy import deepcopy

SCHEMA="r3_agent_story_context_v1"
_COMEBACK_ONLY={"thin_post_climax_tail","development_after_climax",
                "turn_before_opening","sparse_pre_turn_bridge"}

def story_context(plan):
    c=(plan or {}).get("agent_story_context")
    if isinstance(c,dict) and c.get("schema")==SCHEMA:
        return c
    return None

def score_pair(before,after):
    def parse(x):
        if isinstance(x,str):
            x=x.split(":")
        if not isinstance(x,(list,tuple)) or len(x)!=2:
            return None
        try:
            v=tuple(int(i) for i in x)
        except (TypeError,ValueError):
            return None
        return v if all(i>=0 for i in v) else None
    b,a=parse(before),parse(after)
    return (b,a) if b is not None and a is not None else None

def scope_diagnosis(diagnosis,plan,edl):
    """Restrict whole-match goal hypotheses to this story's actual goals.

    Preserve all native integrity, replay, duplication and generic
    transition issues. Required graph nodes are initial hypotheses, not
    video confirmation. Do not invent a goal recovery result.
    """
    c=story_context(plan)
    if c is None:
        return diagnosis
    d=deepcopy(diagnosis)
    targets={score_pair(t["score_before"],t["score_after"]):t for t in c["goal_targets"]}
    targets.pop(None,None)
    active={r["segment_id"]:r for r in edl if r.get("include_in_cut",True) and r.get("media_in") is not None}
    required_ids=sorted({sid for n in c["required_nodes"] for sid in n["segment_ids"] if sid in active})
    # Active rows' membership is authoritative when new edits retain it.
    required_ids=sorted(set(required_ids)|{sid for sid,r in active.items() if r.get("required_story_node_ids")})
    issues=[]; excluded=[]; seen=set()
    for issue in d.get("issues",[]):
        iid=issue.get("issue_id")
        if issue.get("category")=="goal_coverage":
            pair=score_pair(issue.get("score_before"),issue.get("score_after"))
            if pair not in targets:
                excluded.append({"issue_id":iid,"reason":"score_transition_outside_story_goal"})
                continue
            target=targets[pair]
            issue["r3_goal_target"]=deepcopy(target)
            seen.add(pair)
        if c["template_id"]!="comeback" and iid in _COMEBACK_ONLY:
            excluded.append({"issue_id":iid,"reason":"comeback_specific_heuristic"})
            continue
        # A valid one-anchor draft with known missing action is not a request
        # to rerun historical V3-R. Existing goal search handles the omission.
        if iid=="insufficient_media_segments" and active and any(
                n["type"]=="missing" for n in c["required_nodes"]):
            excluded.append({"issue_id":iid,"reason":"known_partial_r3_story_not_rebuild_request"})
            continue
        issues.append(issue)
    d["issues"]=issues
    d["r3_story_context"]=deepcopy(c)
    d["protected_story_segment_ids"]=required_ids
    d["r3_scope_audit"]={"excluded_legacy_issues":excluded,
        "goal_targets":deepcopy(c["goal_targets"]),
        "missing_goal_tasks_without_native_issue":[deepcopy(t) for pair,t in targets.items()
            if t.get("task_id") and pair not in seen],
        "original_goal_recovery_algorithm_unchanged":True}
    return d

def planner_view(diagnosis):
    """Reuse legacy protection contract in Critic/Planner only.

    Original diagnosis still has its actual goal IDs. Do not change shared
    story_timeline.protected_goal_segment_ids or Verifier code.
    """
    if "r3_story_context" not in diagnosis:
        return diagnosis
    return {**diagnosis,"protected_goal_segment_ids":list(dict.fromkeys(
        list(diagnosis.get("protected_goal_segment_ids") or [])+
        list(diagnosis.get("protected_story_segment_ids") or [])))}

def protect_planner_intents(revision,diagnosis,protect_filter):
    """Apply the original protection policy after a real LLM overlay too.

    No additional decision threshold: preserve the existing overturn
    evidence exception and allow all original non-anchor additions.
    """
    if "r3_story_context" not in diagnosis:
        return revision
    before=list(revision.get("revision_intents") or [])
    # Only extend protection to additional graph-required material.
    # Original goal policy is unchanged for legacy and actual goal rows.
    new_ids=set(diagnosis.get("protected_story_segment_ids") or [])-set(
        diagnosis.get("protected_goal_segment_ids") or [])
    after=protect_filter(before,sorted(new_ids))
    if after==before:
        return revision
    out={**revision,"revision_intents":after}
    out["r3_required_anchor_protection"]={"protected_segment_ids":sorted(new_ids),
        "blocked_intent_ids":[r.get("intent_id") for a,r in zip(before,after) if a!=r]}
    if str(out.get("decision")).upper()=="REVISE" and not any(
            i.get("action") not in {"keep","mark_unresolved","unresolved"} for i in after):
        # Same legacy keep-only normalization; not a new quality verdict.
        out["decision"]="UNRESOLVED"
    return out
