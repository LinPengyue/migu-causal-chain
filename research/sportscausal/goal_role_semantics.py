"""R2a.4 scoreboard beneficiary binding, never an execution or attack claim."""
from __future__ import annotations
from collections import Counter
from score_state_patterns import _score
from template_graph import check, number
import re
from episode_semantics import pred, Roles, opposite
from semantic_normalization import resolve, values


def bind_score_outcomes(semantics, score_doc, *, before=180.0, after=15.0):
    if score_doc is None:
        return {"bindings": [], "unresolved": [], "status": "score_path_not_supplied"}
    check(score_doc.get("video_id") == semantics["video_id"], "score path source mismatch")
    mapping = score_doc.get("score_side_mapping")
    check(isinstance(mapping, dict) and set(mapping) == {"left", "right"}
          and set(mapping.values()) == {"team_1", "team_2"}, "explicit score-side mapping required")
    path = score_doc.get("score_path")
    check(isinstance(path, list), "score_path required")
    goals = [a for a in semantics["atoms"] if a["type"] == "Goal" and a["broadcast_phase"] == "LIVE"
             and not cancelled_goal(a)]
    options = []
    for i, node in enumerate(path):
        current = _score(node)
        t = node.get("t_sec")
        check(number(t) and t >= 0, "invalid score time")
        if not i:
            check(node.get("opening") is True, "opening required")
            continue
        old = path[i-1]
        check(t > old["t_sec"] and not node.get("opening"), "nonchronological score path")
        delta = tuple(x-y for x,y in zip(current, _score(old)))
        check(delta in {(1,0), (0,1)}, "nonincremental score path")
        side = "left" if delta == (1,0) else "right"
        check(node.get("delta_side") == side, "score side conflict")
        beneficiary = mapping[side]
        lo, hi = max(0, t-before), t+after
        rows = [a for a in goals if lo <= a["t"] <= hi]
        options.append({"path_index": i, "score_beneficiary": beneficiary, "score_before": old["score"],
                        "score_after": node["score"], "confirmation_t_sec": t,
                        "carrier_event_id": node.get("carrier_event_id"),
                        "previous_score_observed_t_sec": node.get("previous_score_observed_t_sec"),
                        "candidate_ids": [a["event_id"] for a in rows],
                        "search_interval": [lo,hi]})
    uses = Counter(e for x in options for e in x["candidate_ids"])
    by = {a["event_id"]: a for a in goals}
    tentative = [x for x in options if len(x["candidate_ids"]) == 1
                 and uses[x["candidate_ids"][0]] == 1]
    crossing = set()
    for i,a in enumerate(tentative):
        for b in tentative[i+1:]:
            if by[a["candidate_ids"][0]]["t"] >= by[b["candidate_ids"][0]]["t"]:
                crossing.update([a["path_index"], b["path_index"]])
    bindings, unresolved = [], []
    for x in options:
        if x not in tentative or x["path_index"] in crossing:
            unresolved.append({**x, "reason": "missing_or_nonunique_goal_localization"})
            continue
        a = by[x["candidate_ids"][0]]
        bindings.append({**x, "event_id": a["event_id"], "action_t_sec": a["t"],
                         "media_window": a["window"], "basis": "unique_live_goal_and_v3r_score_increment",
                         "causal_verified": False, "first_live_verified": False})
    return {"bindings": bindings, "unresolved": unresolved, "status": "score_path_supplied",
            "score_side_mapping": mapping, "before_sec": before, "after_sec": after}


OWN=re.compile(r"乌龙|own[_ -]?goal",re.I)
CANCELLED=re.compile(r"进球无效|进球被取消|取消进球|判罚进球无效|越位在先|goal[_ -]?(?:disallowed|cancelled|canceled|invalid)",re.I)
GOAL_RESULT_KEYS=("Goal_Type","Goal_Result","Shot_Result","Event_Type","Related_Event")

def cancelled_goal(a):
    return bool(CANCELLED.search(a.get("notes") or "") or
                any(CANCELLED.search(str(v)) for k in GOAL_RESULT_KEYS for v in values(a,k)))

def goal_roles(a, roles, binding=None):
    """Execution claims and score claims are independent, even when they agree."""
    note=a.get("notes") or ""
    own=bool(OWN.search(note) or any(OWN.search(str(v)) for k in GOAL_RESULT_KEYS for v in values(a,k)))
    beneficiary=binding["score_beneficiary"] if binding else None
    cancelled=cancelled_goal(a)
    direct=a.get("execution_actor") or {}
    if own:
        # An explicit actor performing an own goal, not a team benefiting from
        # an opponent's error. Do not use arbitrary BallController attributes.
        pat=re.compile(r"(?P<side>"+roles.side+r")\s*(?:(?P<num>\d{1,2})号)?(?:球员|队员|守门员|门将)?"
            r"(?:(?!"+roles.side+r"|[，。；！？,;.!?]).){0,18}?(?:自摆乌龙|打入乌龙球|踢进乌龙球|乌龙球)")
        claims=[c for c in roles.note_claims(a,pat,execution=True)
                if not re.search(r"被|造成|制造|迫使|获得|受益|的乌龙",c["text"])]
        direct=resolve(claims)
    else:
        # The previous role parser accepts some attributes; only explicit
        # action-language can independently establish execution in this module.
        claims=[c for c in direct.get("claims",[]) if c.get("source")=="notes.role_action"]
        direct=resolve(claims)
    executor=direct.get("team") if not cancelled else None
    conflict=bool(executor and beneficiary and
                  ((own and executor==beneficiary) or (not own and executor!=beneficiary)))
    # No beneficiary-to-execution or beneficiary-to-attack transfer.
    attacking_team=executor if executor and not own and not conflict and not cancelled else None
    return {"score_beneficiary":beneficiary,"goal_executor":executor,
            "attacking_team":attacking_team,
            "goal_kind":"cancelled" if cancelled else "own_goal_explicit" if own else
                        "execution_beneficiary_disagreement" if conflict else
                        "ordinary_goal_annotation" if executor else "untyped_goal",
            "execution_status":direct["team_status"],"execution_claims":direct.get("claims",[]),
            "role_conflict":conflict,
            "score_binding":binding,"first_live_verified":False}
