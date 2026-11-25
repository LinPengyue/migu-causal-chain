"""R2a.3: typed evidence and conditional possession hypotheses."""
from collections import defaultdict
import re
from episode_semantics import opposite, FAILED
from semantic_normalization import resolve

CONTROL = {"Pass", "Ball_possession", "Dribble_past", "Assist"}
BREAK = {"Defensive_action", "Win_an_aerial_duel", "Foul_Being_fouled", "Throw_in",
         "Corner_kick", "Free_kick", "Goal", "Save", "Substitution",
         "Referees_decision", "Full_time"}


def chain_edges(evidence, by):
    """Use original adjacent members; never bridge missing PARTIAL members."""
    out = defaultdict(list)
    for cid, c in sorted(evidence["chains"].items()):
        if c.get("state") not in {"FULL", "PARTIAL"}:
            continue
        ids = c.get("event_ids")
        if not ids and c["state"] == "FULL":
            ids = c.get("available_event_ids", [])
        if not ids or len(ids) != len(set(ids)):
            continue
        avail = set(c.get("available_event_ids", []))
        for x, y in zip(ids, ids[1:]):
            if x in avail and y in avail and x in by and y in by:
                out[(x, y)].append({"chain_id": cid, "state": c["state"], "subtype": c.get("subtype")})
    return out


def possession_actor(a, roles, atom):
    if a["type"] not in CONTROL:
        return None
    pat = re.compile(r"(?P<side>" + roles.side + r")\s*(?:\d{1,2}号)?(?:球员|队员)?"
        r"(?:(?!" + roles.side + r"|[，。；！？,;.!?]).){0,32}?"
        r"(?:传球|传给|传向|直塞|横传|长传|回传|传中|控球|控制球权|控下|带球|拿球|接球|过人)")
    cs = [c for c in roles.note_claims(atom, pat)
          if not FAILED.search(c["text"]) and "被" not in c["text"]]
    cs += roles.claims(atom, ["BallController_player", "BallController_team"])
    return resolve(cs)["team"]


def recovery_claim(b, roles):
    """Explicit receiver and referenced keeper; not generic nearby possession."""
    pat = re.compile(r"(?P<side>" + roles.side + r")\s*(?:\d{1,2}号)?(?:球员|队员)?"
        r"(?:(?!" + roles.side + r"|[，。；！？,;.!?]).){0,24}?"
        r"(?P<keeper>" + roles.side + r")\s*(?:\d{1,2}号)?(?:守门员|门将)(?:\d{1,2}号)?"
        r"(?:扑出|打出|顶出|挡出|托出)(?:的)?球"
        r"(?:(?!" + roles.side + r"|[，。；！？,;.!?]).){0,12}?(?:控下|控制|接到|拿到|补射|射门)")
    note = b.get("notes") or ""
    if FAILED.search(note):
        return None
    pairs = {(roles.aliases[m["side"]], roles.aliases[m["keeper"]]) for m in pat.finditer(note)}
    if len(pairs) != 1:
        return None
    attacker, keeper = next(iter(pairs))
    control_claims = roles.claims(b, ["BallController_player", "BallController_team"])
    if attacker != opposite(keeper) or any(c["team"] != attacker for c in control_claims):
        return None
    return {"attacker": attacker, "keeper": keeper, "event_id": b["event_id"]}


def context_options(order, i, roles, evidence, ci, limit=15.0):
    """Both assignments survive unless independently role-bound. No forced MAP."""
    shot, save = order[i:i+2]
    clues = []
    for direction, anchor, seq in (("before", shot, reversed(order[:i])),
                                    ("after", save, iter(order[i+2:]))):
        middle = []
        for a in seq:
            if abs(a["t"] - anchor["t"]) > limit or a["broadcast_phase"] != "LIVE":
                break
            actor = possession_actor(a, roles, evidence["atoms"][a["event_id"]])
            if actor:
                path = ([a] + list(reversed(middle)) + [shot, save] if direction == "before"
                        else [shot, save] + middle + [a])
                sets = [{z["chain_id"] for z in ci.get((x["event_id"], y["event_id"]), [])}
                        for x, y in zip(path, path[1:])]
                clues.append({"direction": direction, "event_id": a["event_id"], "actor": actor,
                    "intervening_event_ids": [x["event_id"] for x in middle],
                    "possible_turnover": any(x["type"] in BREAK for x in middle),
                    "continuous_chain_ids": sorted(set.intersection(*sets)) if sets else [],
                    "assumption": "attack_continuity" if direction == "before" else "keeper_team_retains_ball"})
                break
            middle.append(a)
    opts = []
    for side in ("team_1", "team_2"):
        h = {"attacker": side, "keeper": opposite(side)}
        h["conditionally_compatible_clues"] = [c["event_id"] for c in clues
            if c["actor"] == h["attacker" if c["direction"] == "before" else "keeper"]]
        h["conditionally_contrary_clues"] = [c["event_id"] for c in clues
            if c["event_id"] not in h["conditionally_compatible_clues"]]
        opts.append(h)
    return {"event_ids": [shot["event_id"], save["event_id"]], "actor_hypotheses": opts,
            "context_clues": clues, "resolved": False, "reason": "context_continuity_not_established"}
