"""R1.1 episode-oriented semantics, separate from the historical event matcher.

All predicates are annotation-grounded hypotheses, not visual or causal proof.
An attempt is not necessarily a dangerous chance; a keeper action is not
necessarily a save. Preserve the historical normalizer for R2b experiments.
"""
from __future__ import annotations
import re
from semantic_normalization import Roles, SHOT, BAD, normalize, resolve, values

SIDES = {"team_1", "team_2"}
STRONG_SAVE = re.compile(r"扑救|扑住|扑出|扑飞|扑到|托出|救险|救球|关键拦截|门线救险")
FAILED = re.compile(r"未能|没能|没有|失败|未果|试图|尝试|无效|被抢断|被截获|被拦截")
SHOT_DANGER = {"Shot_On_Target", "Shot_Post", "Shot_Bar", "Shot_Woodwork",
               "Shot_Hit_Post", "Shot_Hit_Crossbar"}
DELIVERY = r"(?:传中(?:球)?|发出(?:的)?角球|开出(?:的)?角球|开过来的角球|发角球|开角球|发出(?:的)?任意球|开出(?:的)?任意球|发任意球|开任意球)"
DELIVERY_TYPES = {"Pass", "Corner_kick", "Free_kick"}
KEEP_TYPES = {"Save", "Goal_line_clearance", "Defensive_action"}

def opposite(side):
    return "team_2" if side == "team_1" else "team_1" if side == "team_2" else None

def pred(actor, basis):
    return {"actor": actor, "basis": basis} if actor in SIDES else None

def _positive_claims(roles, atom, pattern):
    claims = roles.note_claims(atom, pattern)
    return [c for c in claims if not FAILED.search(c["text"])
            and not re.search(r"被|(?:球员|队员|号)的", c["text"])]

def normalize_for_episodes(evidence):
    result = normalize(evidence)
    roles = Roles(evidence.get("teams"))
    subject = r"(?P<side>"+roles.side+r")\s*(?:(?P<num>\d{1,2})号)?(?:球员|队员)?"
    tail = r"(?:(?!"+roles.side+r"|[，。；！？,;.!?]).){0,24}?"
    continuation = re.compile(subject+tail+r"[，,]\s*(?:选择|随后|接着|直接|顺势|然后|立即|随即)?"+SHOT)
    delivery = re.compile(subject+tail+DELIVERY)
    for row in result["atoms"]:
        a = evidence["atoms"][row["event_id"]]
        note = a.get("notes") or ""
        if not isinstance(note, str):
            note = ""
        p = row["predicates"]
        # Keep earlier state/path predicates available, but rebuild attack/save
        # semantics rather than treating every action as a threatening chance.
        p.pop("goalkeeper_rescue", None)
        p.pop("attacking_threat", None)
        if a.get("broadcast_phase") != "LIVE":
            continue
        typ = a["type"]
        if typ == "Shot":
            row["shooter"] = resolve(_positive_claims(roles,a,roles.shot_action)
                + _positive_claims(roles,a,continuation)
                + roles.claims(a,["BallController_player","BallController_team"]))
            row["attacking_team"] = row["shooter"]
            side = row["shooter"]["team"]
            if side:
                p["attacking_attempt"] = pred(side,"annotated_shot")
                if set(values(a,"Shot_Result")) & SHOT_DANGER:
                    p["attacking_threat"] = pred(side,"annotated_dangerous_shot_result")
        elif typ in DELIVERY_TYPES:
            claims = _positive_claims(roles,a,delivery)
            row["delivery_actor"] = resolve(claims)
            if row["delivery_actor"]["team"]:
                p["attacking_delivery"] = pred(row["delivery_actor"]["team"],"explicit_cross_or_restart")
        elif typ in KEEP_TYPES:
            keeper = row["keeper"]["team"]
            if not keeper:
                continue
            p["goalkeeper_action"] = pred(keeper,"role_bound_keeper_action")
            # A named opponent's shot or delivery in this same description is
            # distinct from merely having an Attacker attribute on a clearance.
            attack_claims = roles.note_claims(a,roles.shot_object)
            attack_claims += roles.note_claims(a,delivery)
            if re.search(r"对手|对方",note) and re.search(r"传向禁区|传中|射门|打门",note):
                attack_claims += roles.claims(a,["Attacker"])
            direct = resolve([c for c in attack_claims if c["team"] != keeper])
            row["direct_attack"] = direct
            if direct["team"]:
                p["attacking_threat"] = pred(direct["team"],"explicit_opponent_action_in_keeper_note")
                p["goalkeeper_rescue"] = pred(keeper,"explicit_opponent_action_in_keeper_note")
            elif STRONG_SAVE.search(note) and not BAD.search(note):
                p["goalkeeper_rescue"] = pred(keeper,"annotated_save_or_critical_interception")
            # Ordinary catches/clearances remain available as keeper_action.
        row["episode_semantics_version"] = "r1.1"
    result["schema"] = "v3r_general_episode_semantics_v1"
    return result
