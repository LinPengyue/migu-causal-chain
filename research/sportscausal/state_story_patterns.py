"""R2b: lift existing score-state matches onto frozen R2a.4 evidence.

A state protagonist, a score beneficiary and an attacking team are distinct.
Score confirmations and uncertain intervals never become clip windows.
"""
from copy import deepcopy
from score_state_patterns import match_score_states
from template_graph import check

def _outcomes(bundle):
    out={}
    for ep in bundle["episodes"]:
        if ep["predicate"]!="scoring_outcome":
            continue
        bindings=ep["goal_score_bindings"]
        check(len(bindings)==1,"expected one score transition per outcome")
        b=bindings[0]
        i=b["path_index"]
        check(i not in out and ep["actor_role"]=="score_beneficiary"
              and ep["actor"]==b["score_beneficiary"],"ambiguous outcome role")
        out[i]=(ep,b)
    return out

def _state_action_interval(i,path,out,missing):
    if i==0:
        return [path[0]["t_sec"],path[0]["t_sec"]]
    if i in out:
        t=out[i][1]["action_t_sec"]
        return [t,t]
    if i in missing:
        return list(missing[i]["search_interval"])
    return None

def state_candidates(template,score_doc,bundle):
    check(score_doc["video_id"]==bundle["video_id"],"score/bundle source mismatch")
    path=score_doc["score_path"]
    out=_outcomes(bundle)
    missing={x["path_index"]:x for x in bundle["goal_bindings"]["unresolved"]}
    tasks=bundle["observation_tasks"]
    for i,(ep,b) in out.items():
        check(0<i<len(path) and b["score_after"]==path[i]["score"]
              and b["score_before"]==path[i-1]["score"]
              and b["confirmation_t_sec"]==path[i]["t_sec"]
              and b["score_beneficiary"]==score_doc["score_side_mapping"][path[i]["delta_side"]],
              "score binding does not match path")
    check(set(out).isdisjoint(missing) and set(out)|set(missing)==set(range(1,len(path))),
          "score transitions not accounted for")
    raw=match_score_states(template,score_doc,bundle["video_id"])
    result=[]
    for c in raw:
        nodes=[]; gaps=[]
        used=set()
        # Every score change in a matched sign run matters, not just the
        # first transition. Opening state is not a goal.
        for run in c["nodes"]:
            for i in run["state_path_indices"]:
                row=path[i]
                node={"node_id":"score:"+str(i),"kind":"score_state",
                      "actor":c["subjects"][0],"actor_role":"state_subject",
                      "state_sign":run["sign"],"score":row["score"],
                      "score_path_index":i,"confirmation_t_sec":row["t_sec"],
                      "event_ids":[],"media_windows":[],"story_anchor":True,
                      "score_beneficiary":None if i==0 else score_doc["score_side_mapping"][row["delta_side"]],
                      "action_time_interval":_state_action_interval(i,path,out,missing),
                      "observation_task_ids":[]}
                if i in out:
                    ep,b=out[i]
                    node.update(event_ids=list(ep["event_ids"]),media_windows=deepcopy(ep["media_windows"]),
                        outcome_episode_id=ep["episode_id"],goal_roles=deepcopy(ep["goal_roles"]),
                        anchor_t=b["action_t_sec"],localization_status="localized_annotation_candidate")
                    used.update(node["event_ids"])
                    node["observation_task_ids"]=[t["task_id"] for t in tasks
                        if t["task_type"]=="goal_execution_roles" and t.get("goal_event_id")==b["event_id"]]
                elif i==0:
                    node.update(localization_status="opening_state_only",story_anchor=False)
                else:
                    node.update(localization_status="missing_action",anchor_t=None,
                        observation_task_ids=[t["task_id"] for t in tasks
                            if t["task_type"]=="missing_goal_localization" and t.get("score_path_index")==i])
                nodes.append(node)
        for a,b in zip(nodes,nodes[1:]):
            left,right=a["action_time_interval"],b["action_time_interval"]
            context=[]
            if left and right and left[1]<right[0]:
                # Only episodes certainly inside both uncertain action
                # boundaries. No inference of dominance or causal influence.
                for ep in bundle["episodes"]:
                    if ep["predicate"] not in {"attacking_threat","goalkeeper_rescue"}:
                        continue
                    if set(ep["event_ids"]) & used:
                        continue
                    if all(left[1]<w[0] and w[1]<right[0] for w in ep["media_windows"]):
                        context.append({"episode_id":ep["episode_id"],"predicate":ep["predicate"],
                            "actor":ep["actor"],"actor_role":ep["actor_role"],
                            "event_ids":ep["event_ids"],"media_windows":ep["media_windows"]})
            gaps.append({"from":a["node_id"],"to":b["node_id"],
                "certain_interior":[left[1],right[0]] if left and right and left[1]<right[0] else None,
                "context_candidates":context,"causal_verified":False})
        result.append({**c,"nodes":nodes,"edges":[{"from":a["node_id"],"to":b["node_id"],
            "relation":"confirmed_score_state_transition","causal_verified":False}
            for a,b in zip(nodes,nodes[1:])],"interval_context":gaps,
            "terminal_basis":"last_confirmed_score_not_independent_final_whistle",
            "unlocalized_state_indices":[n["score_path_index"] for n in nodes if n["localization_status"]=="missing_action"]})
    return result
