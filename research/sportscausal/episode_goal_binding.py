"""R2a.3: score-confirmed goal hypotheses using the existing V3-R score path.

Score observations never become media windows. Bind a transition only to a
uniquely compatible annotated LIVE Goal, not its scoreboard carrier.
"""
from __future__ import annotations
from collections import Counter
from score_state_patterns import _score
from template_graph import check, number
from episode_semantics import pred

def bind_goals(semantics, score_doc, *, before=180.0, after=15.0):
    if score_doc is None:
        return {"bindings":[],"unresolved":[],"status":"score_path_not_supplied"}
    check(score_doc.get("video_id")==semantics["video_id"],"score path source mismatch")
    mapping=score_doc.get("score_side_mapping")
    check(isinstance(mapping,dict) and set(mapping)=={"left","right"}
          and set(mapping.values())=={"team_1","team_2"},"explicit score-side mapping required")
    path=score_doc.get("score_path")
    check(isinstance(path,list),"score_path required")
    goals=[a for a in semantics["atoms"] if a["type"]=="Goal" and a["broadcast_phase"]=="LIVE"
           and not any(s in (a.get("notes") or "") for s in ("乌龙","无效","取消","越位在先"))]
    options=[]
    for i,node in enumerate(path):
        current=_score(node)
        t=node.get("t_sec")
        check(number(t) and t>=0,"invalid score time")
        if not i:
            check(node.get("opening") is True,"opening required")
            continue
        old=path[i-1]
        check(t>old["t_sec"] and not node.get("opening"),"nonchronological score path")
        delta=tuple(x-y for x,y in zip(current,_score(old)))
        check(delta in {(1,0),(0,1)},"nonincremental score path")
        side="left" if delta==(1,0) else "right"
        check(node.get("delta_side")==side,"score side conflict")
        actor=mapping[side]
        # Last old-score observation may lag the action too; record it but
        # do not make an OCR timestamp the action boundary. Adjacent transition
        # candidate sets are checked for uniqueness globally below.
        lo=max(0,t-before)
        hi=t+after
        rows=[]
        conflicts=[]
        for a in goals:
            if not lo<=a["t"]<=hi:
                continue
            # A local score observation is not a goal attribution; do not
            # infer an actor from it. Preserve independent explicit conflicts.
            direct=a.get("execution_actor") or {}
            stated=a["predicates"].get("goal_action",{}).get("actor")
            if direct.get("team_status")=="CONFLICT" or stated and stated!=actor:
                conflicts.append(a["event_id"])
            else:
                rows.append(a)
        options.append({"path_index":i,"actor":actor,"score_before":old["score"],
                        "score_after":node["score"],"confirmation_t_sec":t,
                        "carrier_event_id":node.get("carrier_event_id"),
                        "previous_score_observed_t_sec":node.get("previous_score_observed_t_sec"),
                        "candidate_ids":[a["event_id"] for a in rows],
                        "conflicting_goal_ids":conflicts,"search_interval":[lo,hi]})
    uses=Counter(e for x in options for e in x["candidate_ids"])
    by={a["event_id"]:a for a in goals}
    tentative=[x for x in options if len(x["candidate_ids"])==1 and not x["conflicting_goal_ids"]
               and uses[x["candidate_ids"][0]]==1]
    # Crossing goal/score assignments are ambiguous, never choose nearest.
    crossing=set()
    for i,a in enumerate(tentative):
        for b in tentative[i+1:]:
            if by[a["candidate_ids"][0]]["t"]>=by[b["candidate_ids"][0]]["t"]:
                crossing.update([a["path_index"],b["path_index"]])
    bindings=[]; unresolved=[]
    for x in options:
        if x not in tentative or x["path_index"] in crossing:
            unresolved.append({**x,"reason":"nonunique_or_conflicting_goal_binding"})
            continue
        a=by[x["candidate_ids"][0]]
        bindings.append({**x,"event_id":a["event_id"],"action_t_sec":a["t"],
                         "media_window":a["window"],"basis":"unique_live_goal_and_v3r_score_increment",
                         "causal_verified":False,"first_live_verified":False})
    return {"bindings":bindings,"unresolved":unresolved,"status":"score_path_supplied",
            "score_side_mapping":mapping,"before_sec":before,"after_sec":after}

def apply_goal_bindings(semantics, result):
    by={a["event_id"]:a for a in semantics["atoms"]}
    for b in result["bindings"]:
        a=by[b["event_id"]]
        p=a["predicates"]
        p["goal_action"]=pred(b["actor"],b["basis"])
        p["attacking_threat"]=pred(b["actor"],b["basis"])
        a["goal_score_binding"]=b
    # Independently attributed annotated goals are also outcome evidence.
    for a in semantics["atoms"]:
        if a["type"]=="Goal" and a["broadcast_phase"]=="LIVE" and a["predicates"].get("goal_action"):
            a["predicates"].setdefault("attacking_threat",dict(a["predicates"]["goal_action"]))
