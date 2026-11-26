"""R2a.4 role-safe graph overlay.

Reuse the existing R2a.3 attack/save graph; score outcomes and neutral goal
context are separate from attack relations. Historical graph files stay intact.
"""
from __future__ import annotations
from copy import deepcopy
from episode_semantics import Roles, pred
from episode_relation_evidence import chain_edges
from event_relation_graph import build_relation_graph
from causal_episodes import _actor, _union
from goal_role_semantics import bind_score_outcomes, goal_roles, is_goal, cancelled_goal

def _validate_cache(base,semantics,evidence,use_chains,gap):
    if (base.get("schema")!="v3r_general_relation_graph_v1"
        or base.get("video_id")!=evidence["video_id"]
        or base.get("input_tier")!=evidence["input_tier"]
        or base.get("use_chains")!=use_chains
        or base.get("max_action_gap_sec")!=gap
        or base.get("goal_bindings",{}).get("status")!="score_path_not_supplied"):
        raise ValueError("expected source-matched R2a.3 without-score graph")
    rows={a["event_id"]:a for a in base["atoms"]}
    raw={a["event_id"]:a for a in semantics["atoms"]}
    if len(rows)!=len(base["atoms"]) or set(rows)!=set(raw) or set(rows)!=set(evidence["atoms"]):
        raise ValueError("cache coverage mismatch")
    for eid,a in rows.items():
        if any(a.get(k)!=raw[eid].get(k) for k in
               ("t","window","type","broadcast_phase","notes","attributes","score_observation",
                "keeper","shooter","execution_actor")):
            raise ValueError("cache atom mismatch: "+eid)
    # Do not reuse a graph with prior goal-derived role propagation (even
    # from an independently annotated goal). Caller can build a fresh graph.
    if (any(is_goal(rows[x]) for e in base["edges"] for x in e["event_ids"])
        or any(x.get("score_binding") or is_goal(rows[x["event_id"]])
               for x in base["inferred_roles"])
        or any(a.get("goal_score_binding") for a in rows.values())):
        raise ValueError("cache contains goal-derived relations; omit --base-graph")
    return deepcopy(base)

def build_role_graph(semantics,evidence,score_doc=None,*,base_graph=None,use_chains=True,max_action_gap_sec=5.0):
    if (semantics.get("schema")!="v3r_general_episode_semantics_v1"
        or any(semantics.get(k)!=evidence.get(k) for k in ("video_id","input_tier","teams"))):
        raise ValueError("expected persisted source-matched R1.1 semantics")
    if not 0<max_action_gap_sec<=30:
        raise ValueError("invalid local action gap")
    for a in semantics["atoms"]:
        raw=evidence["atoms"][a["event_id"]]
        if (any(a.get(k)!=raw.get(k) for k in ("t","window","type","broadcast_phase","attributes"))
            or (a.get("notes") or "")!=(raw.get("notes") or "")):
            raise ValueError("source atom mismatch: "+a["event_id"])
    clean=deepcopy(semantics)
    # Prevent the legacy graph from propagating even an explicitly named
    # goal executor to an empty preceding Shot. Restore direct roles later.
    for a in clean["atoms"]:
        if is_goal(a):
            a["predicates"].pop("goal_action",None)
            a["predicates"].pop("attacking_threat",None)
    if base_graph is None:
        base=build_relation_graph(clean,evidence,None,use_chains=use_chains,
                                  max_action_gap_sec=max_action_gap_sec)
        cache_used=False
    else:
        base=_validate_cache(base_graph,clean,evidence,use_chains,max_action_gap_sec)
        cache_used=True
    results=bind_score_outcomes(semantics,score_doc)
    bindings={b["event_id"]:b for b in results["bindings"]}
    original={a["event_id"]:a for a in semantics["atoms"]}
    by={a["event_id"]:a for a in base["atoms"]}
    roles=Roles(evidence.get("teams"))
    ci=chain_edges(evidence,by) if use_chains else {}
    order=sorted(by.values(),key=lambda a:(a["t"],a["event_id"]))
    context=[]; tasks=[]; role_rows=[]
    for i,a in enumerate(order):
        if not is_goal(a):
            continue
        a["predicates"].pop("goal_action",None)
        a["predicates"].pop("attacking_threat",None)
        a.pop("goal_score_binding",None)
        if a["broadcast_phase"]!="LIVE":
            continue
        eid=a["event_id"]
        b=bindings.get(eid)
        r=goal_roles(original[eid],roles,b)
        a["goal_roles"]=r
        role_rows.append({"event_id":eid,**r})
        if r["goal_executor"]:
            a["predicates"]["goal_executor"]=pred(r["goal_executor"],"independent_goal_execution_annotation")
        if r["attacking_team"]:
            a["predicates"]["attacking_threat"]=pred(r["attacking_team"],"independent_goal_action_annotation")
        if b:
            a["predicates"]["scoring_outcome"]=pred(r["score_beneficiary"],b["basis"])
        # A chain may supply a preceding action clip without asserting that
        # the shooter, executor, attack team and beneficiary are identical.
        # This context never enters the attack connected components.
        prior=order[i-1] if i else None
        if (prior and not cancelled_goal(a) and prior["type"]=="Shot" and prior["broadcast_phase"]=="LIVE"
            and 0<a["t"]-prior["t"]<=max_action_gap_sec):
            ids=(prior["event_id"],eid)
            support=ci.get(ids,[])
            if support:
                context.append({"kind":"shot_goal_context","event_ids":list(ids),
                    "chain_support":support,"shooter":_actor(prior,"attacking_attempt"),
                    "goal_executor":r["goal_executor"],"score_beneficiary":r["score_beneficiary"],
                    "attacking_team":r["attacking_team"],
                    "basis":"ordered_local_predicted_members_context_only",
                    "causal_verified":False,"first_live_verified":False})
        if not cancelled_goal(a) and (r["role_conflict"] or not r["goal_executor"] or not r["attacking_team"]):
            ids=[eid]
            if context and context[-1]["event_ids"][-1]==eid:
                ids=context[-1]["event_ids"]
            tasks.append({"task_type":"goal_execution_roles","event_ids":ids,
                "goal_event_id":eid,"score_beneficiary":r["score_beneficiary"],
                "goal_kind":r["goal_kind"],"known_executor":r["goal_executor"],
                "known_attacking_team":r["attacking_team"],
                "role_conflict":r["role_conflict"],
                "media_windows":_union([by[x]["window"] for x in ids]),
                "questions":["identify actual ball-striking team","identify attacking team",
                             "ordinary goal, own goal, or other deflection","confirm first live footage"],
                "reason":"separate execution, attack and score roles","resolved":False})
    for b in results["unresolved"]:
        tasks.append({"task_type":"missing_goal_localization","event_ids":b["candidate_ids"],
            "score_beneficiary":b["score_beneficiary"],"score_path_index":b["path_index"],
            "score_before":b["score_before"],"score_after":b["score_after"],
            "search_interval":b["search_interval"],"confirmation_t_sec":b["confirmation_t_sec"],
            "carrier_event_id":b.get("carrier_event_id"),
            "media_windows":[],"reason":b["reason"],
            "questions":["locate actual goal action and its buildup","verify first live footage",
                         "identify execution and attack roles"],"resolved":False})
    for u in base["unresolved_relations"]:
        ids=u["event_ids"]
        tasks.append({"task_type":"shot_save_roles","event_ids":ids,
            "media_windows":_union([by[x]["window"] for x in ids]),
            "actor_hypotheses":u.get("actor_hypotheses",[]),"context_clues":u.get("context_clues",[]),
            "chain_support":u.get("chain_support",[]),"reason":u.get("reason"),
            "questions":["identify shooting and saving teams","verify action relation",
                         "confirm first live footage"],"resolved":False})
    for j,t in enumerate(tasks,1):
        t["task_id"]="observe:"+str(j)
        t["video_id"]=base["video_id"]
        t["preview_only"]=True
    base.update(schema="v3r_general_role_graph_v1",goal_bindings=results,
                goal_role_claims=role_rows,outcome_context_edges=context,
                observation_tasks=tasks,reused_without_score_graph=cache_used,
                quality_verified=False,first_live_verified=False)
    return base
