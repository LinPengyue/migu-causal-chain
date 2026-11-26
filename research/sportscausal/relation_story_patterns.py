"""R2b: bounded relation-path hypotheses on original predicted member edges.

A complete local path is not a proved possession or a causal relation.
PARTIAL chains supply only contiguous available members. Never stitch two
unrelated chains, skip missing positions or equate a beneficiary with a shooter.
"""
import re
from collections import defaultdict
from copy import deepcopy
from causal_episodes import _actor, _union
from episode_semantics import Roles, FAILED
from episode_relation_evidence import chain_edges, possession_actor
from semantic_normalization import resolve
from goal_role_semantics import is_goal
from template_graph import check, number

RESTART={"Corner_kick","Free_kick","Penalty","Throw_in","Kick_off"}
STOP={"Foul_Being_fouled","Referees_decision","Full_time","Half_time","Offside","Substitution"}
TURNOVER_ACTION=re.compile(r"抢断|截获|断下|抢下|夺回球权|夺回皮球")

def turnover_actor(a,roles):
    if a["type"]!="Defensive_action":
        return None
    note=a.get("notes") or ""
    if FAILED.search(note):
        return None
    pat=re.compile(r"(?P<side>"+roles.side+r")\s*(?:(?P<num>\d{1,2})号)?(?:球员|队员)?"
        r"(?:(?!"+roles.side+r"|[，。；！？,;.!?]).){0,24}?(?:"+TURNOVER_ACTION.pattern+r")")
    claims=[c for c in roles.note_claims(a,pat,execution=True)
            if not re.search(r"被|的抢断|的截获|试图|尝试",c["text"])]
    claims+=roles.claims(a,["Defender"]) if claims else []
    return resolve(claims)["team"]

def _start(a,p,roles):
    if p=="set_piece_execution":
        return _actor(a,p) if a["type"] in {"Corner_kick","Free_kick","Penalty"} else None
    if p=="turnover_recovery":
        return turnover_actor(a,roles)
    if p=="attacking_attempt":
        return _actor(a,p)
    raise ValueError("unsupported relation start "+p)

def _goal_endpoint(a):
    r=a.get("goal_roles") or {}
    if not is_goal(a) or r.get("goal_kind")=="cancelled":
        return None
    return r

def _validate(p):
    check(p["operator"]=="relation_path" and p["start_predicate"] in
          {"set_piece_execution","turnover_recovery","attacking_attempt"} and
          p["end_predicate"]=="scoring_outcome","unsupported role path pattern")
    for k,upper in (("max_span_sec",180),("max_edge_gap_sec",60)):
        check(number(p.get(k)) and 0<p[k]<=upper,"invalid path time bound")
    check(p["max_edge_gap_sec"]<=p["max_span_sec"],"edge gap exceeds path span")
    return p

def relation_candidates(template,graph,evidence):
    p=_validate(template["pattern"])
    check(graph["video_id"]==evidence["video_id"] and graph["input_tier"]==evidence["input_tier"],
          "relation source mismatch")
    by={a["event_id"]:a for a in graph["atoms"]}
    check(set(by)==set(evidence["atoms"]),"relation atom coverage mismatch")
    roles=Roles(evidence.get("teams"))
    order=sorted(by.values(),key=lambda a:(a["t"],a["event_id"]))
    order_index={a["event_id"]:i for i,a in enumerate(order)}
    ci=chain_edges(evidence,by)
    typed={tuple(e["event_ids"]):e for e in graph["edges"]}
    context={tuple(e["event_ids"]):e for e in graph["outcome_context_edges"]}
    explicit_conflicts={tuple(e["event_ids"]) for e in graph["rejected_edges"]
                        if e.get("reason") in {"actor_conflict","keeper_conflict","shooter_conflict",
                                               "recovery_reference_conflict"}}
    adjacency=defaultdict(list)
    for (x,y),support in ci.items():
        a,b=by[x],by[y]
        if (x,y) in explicit_conflicts:
            continue
        if a["broadcast_phase"]!="LIVE" or b["broadcast_phase"]!="LIVE":
            continue
        if not 0<b["t"]-a["t"]<=p["max_edge_gap_sec"]:
            continue
        adjacency[x].append((y,{z["chain_id"] for z in support}))
    pairs={}
    for start in order:
        actor=_start(start,p["start_predicate"],roles)
        if not actor or start["broadcast_phase"]!="LIVE":
            continue
        # A DAG path must maintain a common original predicted chain ID.
        stack=[([start["event_id"]],None)]
        while stack:
            ids,common=stack.pop()
            a=by[ids[-1]]
            for y,support in adjacency.get(ids[-1],[]):
                b=by[y]
                shared=support if common is None else common & support
                if not shared or b["t"]-start["t"]>p["max_span_sec"]:
                    continue
                # Intervening global atoms can invalidate a broad chain.
                # Ignore neither an unselected restart nor an unselected goal.
                mid=order[order_index[ids[-1]]+1:order_index[y]]
                def interrupts(row):
                    if row["broadcast_phase"]!="LIVE" or row["type"] in STOP|RESTART or is_goal(row):
                        return True
                    observed=possession_actor(row,roles,evidence["atoms"][row["event_id"]])
                    gain=turnover_actor(row,roles)
                    attacking=[_actor(row,k) for k in ("attacking_attempt","attacking_delivery","attacking_threat")]
                    return bool(observed and observed!=actor or gain and gain!=actor
                                or any(side and side!=actor for side in attacking))
                if any(interrupts(row) for row in mid):
                    continue
                trail=ids+[y]
                if is_goal(b):
                    r=_goal_endpoint(b)
                    if not r or r.get("role_conflict") or r.get("score_beneficiary")!=actor:
                        continue
                    if r.get("attacking_team") and r["attacking_team"]!=actor:
                        continue
                    key=tuple(trail)
                    if key not in pairs:
                        pairs[key]={"actor":actor,"ids":trail,"chain_ids":set(),
                                    "endpoint_roles":deepcopy(r)}
                    pairs[key]["chain_ids"].update(shared)
                    continue
                if interrupts(b):
                    continue
                # The next explicit start replaces the earlier starting point.
                # Keep a different same-side control action as path context.
                if _start(b,p["start_predicate"],roles):
                    continue
                shot=_actor(b,"attacking_attempt")
                if shot and shot!=actor:
                    continue
                stack.append((trail,shared))
    # For the same start/end, preserve distinct intermediate paths, but
    # group them as alternative hypotheses instead of duplicate stories.
    endpoints=defaultdict(list)
    for r in pairs.values():
        endpoints[(r["ids"][0],r["ids"][-1])].append(r)
    result=[]
    for key,alts in sorted(endpoints.items(),key=lambda kv:(by[kv[0][0]]["t"],by[kv[0][1]]["t"],kv[0])):
        alternatives=[]
        for r in sorted(alts,key=lambda x:x["ids"]):
            ids=r["ids"]
            links=[]
            for x,y in zip(ids,ids[1:]):
                k=(x,y)
                support=[z for z in ci[k] if z["chain_id"] in r["chain_ids"]]
                links.append({"from":x,"to":y,"relation":"ordered_predicted_members",
                    "chain_support":support,"typed_local_relation":deepcopy(typed.get(k) or context.get(k)),
                    "causal_verified":False})
            alternatives.append({"event_ids":ids,"path_chain_ids":sorted(r["chain_ids"]),
                "media_windows":_union([by[x]["window"] for x in ids]),"links":links,
                "intermediate_event_ids":ids[1:-1]})
        r=alts[0]
        start,end=(by[x] for x in key)
        nodes=[{"node_id":"start","kind":"relation_start","actor":r["actor"],
            "actor_role":"restart_executor" if p["start_predicate"]=="set_piece_execution" else
                         "ball_recovery_team" if p["start_predicate"]=="turnover_recovery" else "shooter",
            "predicate":p["start_predicate"],"event_ids":[key[0]],"anchor_t":start["t"],
            "media_windows":[start["window"]],"story_anchor":True},
            {"node_id":"outcome","kind":"score_outcome","actor":r["endpoint_roles"]["score_beneficiary"],
             "actor_role":"score_beneficiary","predicate":"scoring_outcome","event_ids":[key[1]],
             "anchor_t":end["t"],"media_windows":[end["window"]],"goal_roles":[r["endpoint_roles"]],
             "story_anchor":True}]
        task_ids=[t["task_id"] for t in graph["observation_tasks"]
                  if t.get("goal_event_id")==key[1]]
        result.append({"candidate_id":template["template_id"]+":"+str(len(result)+1),
            "subjects":[r["actor"]],"nodes":nodes,
            "edges":[{"from":"start","to":"outcome","relation":"predicted_relation_path_hypothesis",
                      "causal_verified":False}],"path_alternatives":alternatives,
            "observation_task_ids":task_ids,
            "requires_path_video_verification":True,
            "scope":"start actor and score beneficiary align; execution and tactical causal link require observation",
            "quality_verified":False,"first_live_verified":False,"release_authorized":False})
    return result
