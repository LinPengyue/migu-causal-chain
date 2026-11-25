"""R2a.1: local predicted-chain-supported attack/outcome hypotheses.

Never interpret a whole predicted window as one possession. A PARTIAL chain
can support a *local* pair only when both IDs were consecutive in its
original member list, are present, and satisfy independent semantic/time
constraints. The pair is still a hypothesis, not a completed chain.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from episode_semantics import opposite, pred, KEEP_TYPES, FAILED
from semantic_normalization import values

SAVE_CHAINS = {"shot_save_chain", "goal_line_extreme_save_chain"}
NON_SAVE_RESULTS = {"Shot_Wide", "Shot_Post", "Shot_Bar", "Shot_Woodwork",
                    "Shot_Hit_Post", "Shot_Hit_Crossbar"}
PROJECTIONS = ("goalkeeper_action", "goalkeeper_rescue", "attacking_attempt", "attacking_threat")

def _actor(a, key):
    return a["predicates"].get(key,{}).get("actor")

def _empty_role(a, key):
    # Do not override explicit conflict or failed/ambiguous narrative evidence.
    return (a.get(key,{}).get("team_status") == "UNRESOLVED"
            and not a.get("notes") and not a.get("attributes"))

def _candidate_pair(a,b,evidence,max_action_gap_sec):
    if a["broadcast_phase"] != "LIVE" or b["broadcast_phase"] != "LIVE":
        return None,"nonlive"
    if not 0 < b["t"]-a["t"] <= max_action_gap_sec:
        return None,"action_gap"
    if b["window"][0] > a["window"][1]+max_action_gap_sec:
        return None,"window_gap"
    if b["type"] not in KEEP_TYPES:
        return None,"not_keeper_outcome"
    keeper=_actor(b,"goalkeeper_action")
    if FAILED.search(b.get("notes") or ""):
        return None,"failed_or_passive_outcome"
    if b["type"]!="Save" and not keeper:
        return None,"unbound_non_save"
    if b.get("keeper",{}).get("team_status")=="CONFLICT":
        return None,"keeper_conflict"
    if a["type"]=="Shot":
        kind="shot_save"
        attacker=_actor(a,"attacking_attempt")
        if set(values(evidence["atoms"][a["event_id"]],"Shot_Result")) & NON_SAVE_RESULTS:
            return None,"incompatible_shot_result"
        if a.get("shooter",{}).get("team_status")=="CONFLICT":
            return None,"shooter_conflict"
        # Missing explicit actor can be inferred only for empty annotations.
        if not attacker and not _empty_role(a,"shooter"):
            return None,"ambiguous_shooter"
        if not keeper and not _empty_role(b,"keeper"):
            return None,"ambiguous_keeper"
    elif _actor(a,"attacking_delivery") and keeper:
        kind="delivery_keeper"
        attacker=_actor(a,"attacking_delivery")
    else:
        return None,"not_shot_or_explicit_delivery"
    direct=_actor(b,"attacking_threat")
    if (attacker and keeper and attacker==keeper
        or direct and attacker and direct!=attacker
        or direct and keeper and direct==keeper):
        return None,"actor_conflict"
    attacker=attacker or direct
    if kind=="shot_save":
        # One-hop opposite role transfer. Never iterate this inference, never
        # infer a player number, and never force a team if both are missing.
        attacker=attacker or opposite(keeper)
        keeper=keeper or opposite(attacker)
    return {"kind":kind,"event_ids":[a["event_id"],b["event_id"]],
            "attacker":attacker,"keeper":keeper,
            "inferred_shooter":kind=="shot_save" and bool(attacker) and not _actor(a,"attacking_attempt"),
            "inferred_keeper":bool(keeper) and not _actor(b,"goalkeeper_action"),
            "causal_verified":False},None

def build_episodes(semantics,evidence,*,use_chains=True,max_action_gap_sec=5.0):
    if not 0 < max_action_gap_sec <= 30:
        raise ValueError("invalid local action gap")
    if semantics["video_id"] != evidence["video_id"]:
        raise ValueError("source mismatch")
    rows=deepcopy(semantics["atoms"])
    by={a["event_id"]:a for a in rows}
    order=sorted(rows,key=lambda a:(a["t"],a["event_id"]))
    idx={a["event_id"]:i for i,a in enumerate(order)}
    links={}
    rejected=[]
    if use_chains:
        for cid,c in sorted(evidence["chains"].items()):
            if c.get("state") not in {"FULL","PARTIAL"} or c.get("subtype") not in SAVE_CHAINS:
                continue
            original=c.get("event_ids")
            # A partial compact request may not retain missing member positions.
            # Do not guess adjacency from its available list.
            if not original:
                if c["state"]=="FULL":
                    original=c.get("available_event_ids",[])
                else:
                    rejected.append({"chain_id":cid,"reason":"missing_original_member_order"})
                    continue
            available=set(c.get("available_event_ids",[]))
            for x,y in zip(original,original[1:]):
                if x not in available or y not in available or x not in by or y not in by:
                    continue
                a,b=by[x],by[y]
                # Distinct attacks can occur inside broad predicted windows.
                # Also reject intervening *global* eligible atomic events.
                if not (a["type"]=="Shot" or _actor(a,"attacking_delivery")) or b["type"] not in KEEP_TYPES:
                    continue
                if idx[y] != idx[x]+1:
                    rejected.append({"chain_id":cid,"event_ids":[x,y],"reason":"intervening_or_reversed_atom"})
                    continue
                link,reason=_candidate_pair(a,b,evidence,max_action_gap_sec)
                if not link:
                    rejected.append({"chain_id":cid,"event_ids":[x,y],"reason":reason})
                    continue
                key=(x,y)
                if key not in links:
                    links[key]={**link,"chain_support":[]}
                links[key]["chain_support"].append({"chain_id":cid,"state":c["state"],"subtype":c["subtype"]})
    linked=sorted(links.values(),key=lambda l:(by[l["event_ids"][0]]["t"],l["event_ids"]))
    # All link hypotheses are computed from immutable direct semantics.
    # Distinct pairs cannot share endpoints; do not propagate across a graph.
    counts=defaultdict(int)
    for l in linked:
        for eid in l["event_ids"]:
            counts[eid]+=1
    used=set()
    projected=[]
    accepted=[]
    for l in linked:
        ids=l["event_ids"]
        if any(counts[i]>1 for i in ids):
            rejected.append({"event_ids":ids,"reason":"competing_local_pairs"})
            continue
        if not l["attacker"] or not l["keeper"]:
            rejected.append({"event_ids":ids,"reason":"both_roles_missing","chain_support":l["chain_support"]})
            continue
        a,b=(by[i] for i in ids)
        accepted.append(l)
        used.update(ids)
        if l["inferred_shooter"]:
            a["predicates"]["attacking_attempt"]=pred(l["attacker"],"one_hop_predicted_save_pair")
        if l["inferred_keeper"]:
            b["predicates"]["goalkeeper_action"]=pred(l["keeper"],"one_hop_predicted_save_pair")
        # Shot-save is an annotated candidate threat/rescue; a delivery-catch
        # alone is a local association, not evidence of critical danger.
        if l["kind"]=="shot_save":
            a["predicates"]["attacking_threat"]=pred(l["attacker"],"local_predicted_shot_save_pair")
            b["predicates"]["goalkeeper_rescue"]=pred(l["keeper"],"local_predicted_shot_save_pair")
        actors=defaultdict(set)
        for row in (a,b):
            for p in PROJECTIONS:
                side=_actor(row,p)
                if side:
                    actors[p].add(side)
        for p,sides in actors.items():
            if len(sides)!=1:
                rejected.append({"event_ids":ids,"predicate":p,"reason":"projection_actor_conflict"})
                continue
            side=next(iter(sides))
            core=[r["event_id"] for r in (a,b) if _actor(r,p)==side]
            projected.append(_episode(p,side,[a,b],core,l))
    # Direct atomic evidence remains usable even when chains are absent.
    # Keep all projections, including ordinary actions and shot attempts.
    for a in rows:
        if a["event_id"] in used:
            continue
        for p in PROJECTIONS:
            side=_actor(a,p)
            if side:
                projected.append(_episode(p,side,[a],[a["event_id"]],None))
    # Historical overlap proxy only for unlinked, same-side, same-predicate
    # windows. Never merge two distinct accepted shot/outcome pairs.
    grouped=defaultdict(list)
    for ep in projected:
        grouped[(ep["predicate"],ep["actor"])].append(ep)
    episodes=[]
    for _,group in sorted(grouped.items()):
        merged=[]
        for ep in sorted(group,key=lambda e:(e["window"][0],e["anchor_t"],e["event_ids"])):
            if (merged and not merged[-1]["relation"] and not ep["relation"]
                and ep["window"][0]<merged[-1]["window"][1]):
                old=merged[-1]
                old["event_ids"]+=ep["event_ids"]
                old["core_event_ids"]+=ep["core_event_ids"]
                old["window"][1]=max(old["window"][1],ep["window"][1])
                old["media_windows"]=_union(old["media_windows"]+ep["media_windows"])
                old["anchor_t"]=min(old["anchor_t"],ep["anchor_t"])
                old["score_observations"]+=ep["score_observations"]
            else:
                merged.append(ep)
        episodes.extend(merged)
    episodes.sort(key=lambda e:(e["anchor_t"],e["predicate"],e["actor"],e["event_ids"]))
    for i,ep in enumerate(episodes,1):
        ep["episode_id"]="episode:"+str(i)
    return {"schema":"v3r_general_causal_episodes_v1","video_id":evidence["video_id"],
            "input_tier":evidence["input_tier"],"use_chains":use_chains,
            "max_action_gap_sec":max_action_gap_sec,"episodes":episodes,
            "local_links":accepted,"rejected_links":rejected,
            "inferred_roles":[{"event_id":l["event_ids"][i],"role":role,"actor":l[key],
                               "support_event_ids":l["event_ids"],"chain_support":l["chain_support"]}
                              for l in accepted for i,role,key,flag in (
                                  (0,"shooter","attacker","inferred_shooter"),
                                  (1,"keeper","keeper","inferred_keeper")) if l[flag]],
            "first_live_verified":False,"quality_verified":False}

def _union(windows):
    result=[]
    for lo,hi in sorted(windows):
        if result and lo<=result[-1][1]:
            result[-1][1]=max(result[-1][1],hi)
        else:
            result.append([lo,hi])
    return result

def _episode(predicate,actor,rows,core,relation):
    windows=_union([a["window"] for a in rows])
    return {"predicate":predicate,"actor":actor,"event_ids":[a["event_id"] for a in rows],
            "core_event_ids":core,"anchor_t":min(a["t"] for a in rows if a["event_id"] in core),
            "window":[windows[0][0],windows[-1][1]],"media_windows":windows,
            "score_observations":[{"event_id":a["event_id"],"score":a["score_observation"]}
                                  for a in rows if a.get("score_observation") is not None],
            "relation":relation,"causal_verified":False,
            "distinct_episode_basis":"local_predicted_relation" if relation else "atomic_window_proxy"}
