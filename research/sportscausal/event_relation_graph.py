"""R2a.3 typed relations and multi-event evidence, not full possession reconstruction."""
from __future__ import annotations
from copy import deepcopy
import re
from episode_semantics import Roles, opposite, pred, KEEP_TYPES
from semantic_normalization import values
from causal_episodes import _candidate_pair, _actor
from episode_goal_binding import bind_goals, apply_goal_bindings
from episode_relation_evidence import chain_edges, context_options, recovery_claim, CONTROL

DEFLECT = re.compile(r"打出|扑出|扑飞|挡出|顶出|托出|解围|踢走|推出")
FOLLOW = re.compile(r"接球|补射|再射|再次射门|二次进攻|拿球|控下|控制")
OFF = {"Shot_Wide", "Shot_Post", "Shot_Bar", "Shot_Woodwork", "Shot_Hit_Post", "Shot_Hit_Crossbar"}


def edge(kind, a, b, support, basis, attacker=None, keeper=None, **extra):
    return {"kind": kind, "event_ids": [a["event_id"], b["event_id"]], "attacker": attacker,
            "keeper": keeper, "basis": basis, "chain_support": support, "causal_verified": False, **extra}


def build_relation_graph(semantics, evidence, score_doc=None, *, use_chains=True, max_action_gap_sec=5.0):
    if not 0 < max_action_gap_sec <= 30:
        raise ValueError("invalid action gap")
    if any(semantics.get(k) != evidence.get(k) for k in ("video_id", "input_tier", "teams")):
        raise ValueError("source mismatch")
    if semantics.get("schema") != "v3r_general_episode_semantics_v1":
        raise ValueError("persisted R1.1 semantics required")
    s = deepcopy(semantics)
    by = {a["event_id"]: a for a in s["atoms"]}
    if len(by) != len(s["atoms"]) or set(by) != set(evidence["atoms"]):
        raise ValueError("coverage mismatch")
    for eid, a in by.items():
        b = evidence["atoms"][eid]
        if (any(a.get(k) != b.get(k) for k in ("t", "window", "type", "broadcast_phase", "attributes"))
            or (a.get("notes") or "") != (b.get("notes") or "")):
            raise ValueError("source atom mismatch: " + eid)
    goals = bind_goals(s, score_doc)
    apply_goal_bindings(s, goals)
    roles = Roles(evidence.get("teams"))
    order = sorted(by.values(), key=lambda a: (a["t"], a["event_id"]))
    ci = chain_edges(evidence, by) if use_chains else {}
    proposals, rejected, unresolved = [], [], []
    # Generate proposals from immutable direct evidence + score-bound goals.
    # Never turn an inferred predicate into a new unrelated proposal.
    for i, (a,b) in enumerate(zip(order, order[1:])):
        ids = (a["event_id"], b["event_id"])
        support = ci.get(ids, [])
        if (a["broadcast_phase"] != "LIVE" or b["broadcast_phase"] != "LIVE"
            or not 0 < b["t"]-a["t"] <= max_action_gap_sec):
            continue
        atk = _actor(a,"attacking_attempt") or _actor(a,"attacking_delivery")
        keep = _actor(b,"goalkeeper_action")
        if (a["type"] == "Shot" or _actor(a,"attacking_delivery")) and b["type"] in KEEP_TYPES:
            # A no-chain control can use the same independently observed local pair.
            # Predicted members can additionally support a role-missing pair.
            if support or (atk and keep and atk == opposite(keep)):
                l, reason = _candidate_pair(a,b,evidence,max_action_gap_sec)
                if not l:
                    rejected.append({"event_ids":list(ids),"reason":reason,"chain_support":support})
                elif not l["attacker"] or not l["keeper"]:
                    # Explicit cross-reference in a third adjacent action can resolve
                    # the missing roles; mere nearest possession cannot.
                    c = order[i+2] if i+2 < len(order) else None
                    recovery = (recovery_claim(c,roles) if c and c["type"] in CONTROL|{"Shot"}
                                and c["broadcast_phase"] == "LIVE" and 0<c["t"]-b["t"]<=max_action_gap_sec
                                and (c["type"]=="Shot" or "禁区" in (c.get("notes") or "")) else None)
                    if (support and recovery and ci.get((b["event_id"],c["event_id"]))
                        and (not l["attacker"] or l["attacker"] == recovery["attacker"])
                        and (not l["keeper"] or l["keeper"] == recovery["keeper"])):
                        l.update(attacker=recovery["attacker"], keeper=recovery["keeper"],
                                 inferred_shooter=not _actor(a,"attacking_attempt"),
                                 inferred_keeper=not _actor(b,"goalkeeper_action"))
                        proposals.append(edge("shot_save",a,b,support,"explicit_third_event_role_reference",
                            l["attacker"],l["keeper"],inferred_shooter=l["inferred_shooter"],
                            inferred_keeper=l["inferred_keeper"],reference_event_id=c["event_id"]))
                        proposals.append(edge("keeper_deflection_followup",b,c,ci[(b["event_id"],c["event_id"])],
                            "explicit_recovery_reference",l["attacker"],l["keeper"]))
                    else:
                        unresolved.append({**context_options(order,i,roles,evidence,ci),"chain_support":support})
                else:
                    proposals.append(edge(l["kind"],a,b,support,"local_role_compatible_action_pair",
                        l["attacker"],l["keeper"],inferred_shooter=l["inferred_shooter"],
                        inferred_keeper=l["inferred_keeper"]))
            elif a["type"]=="Shot" and b["type"]=="Save" and not atk and not keep:
                # Log the neutral hypothesis even when the predicted edges are removed.
                unresolved.append({**context_options(order,i,roles,evidence,ci),"chain_support":[],
                                   "relation_support":"raw_temporal_candidate_only"})
        keep = _actor(a,"goalkeeper_action")
        if keep and b["type"] in CONTROL|{"Shot"} and DEFLECT.search(a.get("notes") or ""):
            ref = recovery_claim(b,roles)
            direct = ref and ref["keeper"] == keep and ref["attacker"] == opposite(keep)
            follow = _actor(b,"attacking_attempt") if b["type"]=="Shot" else None
            # A contested box recovery / follow-up shot may be a continuing threat.
            if ref and not direct:
                rejected.append({"event_ids":list(ids),"reason":"recovery_reference_conflict","chain_support":support})
            elif ((direct and (b["type"]=="Shot" or "禁区" in (b.get("notes") or "")))
                or (support and follow==opposite(keep) and FOLLOW.search(b.get("notes") or ""))):
                if not follow or follow==opposite(keep):
                    proposals.append(edge("keeper_deflection_followup",a,b,support,
                        "explicit_recovery_reference" if direct else "chain_supported_followup",opposite(keep),keep))
        if a["type"]=="Shot" and b["type"]=="Goal" and _actor(b,"goal_action"):
            actor = _actor(b,"goal_action")
            direct = _actor(a,"attacking_attempt")
            if (set(values(evidence["atoms"][a["event_id"]],"Shot_Result")) & OFF
                or re.search(r"射偏|打偏|门柱|横梁|无效|取消",a.get("notes") or "")
                or direct and direct!=actor or a.get("shooter",{}).get("team_status")=="CONFLICT"):
                rejected.append({"event_ids":list(ids),"reason":"shot_goal_conflict","chain_support":support})
                continue
            if support or direct==actor:
                if not direct and (a.get("notes") or a.get("attributes")
                                   or a.get("shooter",{}).get("team_status")!="UNRESOLVED"):
                    continue
                proposals.append(edge("shot_goal",a,b,support,"localized_goal_and_compatible_shot",actor,
                    inferred_shooter=not direct,score_binding=b.get("goal_score_binding")))
    # Adjacent edges only. Build compatible same-attack paths, not an unrestricted
    # connected component of the original predicted chain. Contradictory proposals
    # that touch an event are all excluded; retain direct evidence for that event.
    # A path may not continue through a Goal or a non-deflection Save.
    order_idx = {a["event_id"]:i for i,a in enumerate(order)}
    proposals.sort(key=lambda e:(order_idx[e["event_ids"][0]],e["kind"]))
    bad = set()
    for i,e in enumerate(proposals):
        for j,f in enumerate(proposals[i+1:],i+1):
            shared = set(e["event_ids"]) & set(f["event_ids"])
            if not shared:
                continue
            incompatible = (e["attacker"]!=f["attacker"] or
                e.get("keeper") and f.get("keeper") and e["keeper"]!=f["keeper"] or
                e["event_ids"]==f["event_ids"] or
                any(by[x]["type"]=="Goal" for x in shared))
            if incompatible:
                bad.update([i,j])
    # Keep third-event dependencies atomic. If the reference edge is excluded,
    # exclude the dependent two-event role transfer too.
    for i,e in enumerate(proposals):
        if e.get("reference_event_id"):
            ref_ids=[e["event_ids"][1],e["reference_event_id"]]
            if not any(j not in bad and f["event_ids"]==ref_ids for j,f in enumerate(proposals)):
                bad.add(i)
    links = [e for i,e in enumerate(proposals) if i not in bad]
    rejected += [{**e,"reason":"incompatible_overlapping_relation_hypotheses"}
                 for i,e in enumerate(proposals) if i in bad]
    inferred = []
    for l in links:
        a,b = (by[x] for x in l["event_ids"])
        pa,pb = a["predicates"],b["predicates"]
        atk,keep = l["attacker"],l.get("keeper")
        for row,key,role,actor,flag in ((a,"attacking_attempt","shooter",atk,l.get("inferred_shooter")),
                                       (b,"goalkeeper_action","keeper",keep,l.get("inferred_keeper"))):
            if flag:
                row["predicates"][key]=pred(actor,l["basis"])
                inferred.append({"event_id":row["event_id"],"role":role,"actor":actor,
                    "support_event_ids":l["event_ids"]+([l["reference_event_id"]] if l.get("reference_event_id") else []),
                    "chain_support":l["chain_support"],"score_binding":l.get("score_binding")})
        if l["kind"]=="shot_save":
            pa.setdefault("attacking_threat",pred(atk,"local_shot_save_relation"))
            pb.setdefault("goalkeeper_rescue",pred(keep,"local_shot_save_relation"))
        elif l["kind"]=="keeper_deflection_followup":
            pa.setdefault("goalkeeper_rescue",pred(keep,"deflection_and_opponent_followup"))
            pb.setdefault("attacking_threat",pred(atk,"opponent_followup_after_keeper_deflection"))
        elif l["kind"]=="shot_goal":
            pa.setdefault("attacking_threat",pred(atk,"shot_goal_relation"))
    for l in links:
        if l["kind"]=="delivery_keeper":
            a,b=(by[e] for e in l["event_ids"])
            if _actor(b,"goalkeeper_rescue")==l["keeper"]:
                a["predicates"].setdefault("attacking_threat",pred(l["attacker"],"delivery_to_annotated_rescue"))
    return {"schema":"v3r_general_relation_graph_v1","video_id":s["video_id"],"input_tier":s["input_tier"],
            "use_chains":use_chains,"max_action_gap_sec":max_action_gap_sec,"atoms":s["atoms"],
            "edges":links,"rejected_edges":rejected,"unresolved_relations":unresolved,
            "inferred_roles":inferred,"goal_bindings":goals,"quality_verified":False,"first_live_verified":False}
