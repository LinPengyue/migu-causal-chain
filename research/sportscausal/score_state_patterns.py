"""Generic state-transition matcher over the *existing* V3-R score_path.

No OCR, goal localization, score imputation or editing. Score nodes are
confirmation anchors, never executable clip boundaries. Source and explicit
scoreboard-side binding must be supplied by the caller.
"""
from __future__ import annotations

import re
from template_graph import check, number

SCORE = re.compile(r"\s*(\d+)\s*[:：]\s*(\d+)\s*")

def validate_state_pattern(p):
    check(set(p)=={"operator","signs","terminal_sign","selection"},"invalid state pattern")
    signs=p["signs"]
    check(isinstance(signs,list) and len(signs)>=2 and
          all(type(x) is int and x in {-1,0,1} for x in signs) and
          all(a!=b for a,b in zip(signs,signs[1:])),"invalid state sign sequence")
    check(p["terminal_sign"] is None or type(p["terminal_sign"]) is int and
          p["terminal_sign"] in {-1,0,1},"invalid terminal sign")
    check(p["selection"] in {"all","last"},"invalid candidate selection")
    return p

def _score(row):
    value=row.get("score")
    m=SCORE.fullmatch(value) if isinstance(value,str) else None
    check(m is not None,"invalid confirmed score")
    return int(m[1]),int(m[2])

def match_score_states(template,score_doc,video_id):
    p=validate_state_pattern(template["pattern"])
    check(score_doc.get("video_id")==video_id,"score path source mismatch")
    mapping=score_doc.get("score_side_mapping")
    check(isinstance(mapping,dict) and set(mapping)=={"left","right"} and
          set(mapping.values())=={"team_1","team_2"},"explicit scoreboard side mapping required")
    path=score_doc.get("score_path")
    check(isinstance(path,list),"confirmed score_path required")
    prior=None
    for i,row in enumerate(path):
        score=_score(row)
        check(number(row.get("t_sec")) and row["t_sec"]>=0,"invalid score confirmation time")
        if i==0:
            check(row.get("opening") is True,"expected opening score node")
        else:
            check(row["t_sec"]>path[i-1]["t_sec"],"score path must be strictly chronological")
            delta=tuple(a-b for a,b in zip(score,prior))
            check(delta in {(1,0),(0,1)},"non-incremental score path")
            check(row.get("delta_side")==("left" if delta==(1,0) else "right"),"score side mismatch")
        prior=score
    result=[]
    for side in ("left","right"):
        sign=lambda row: ((1 if side=="left" else -1)*(_score(row)[0]-_score(row)[1]))
        runs=[]
        for i,row in enumerate(path):
            margin=sign(row)
            state=(margin>0)-(margin<0)
            if not runs or runs[-1]["sign"]!=state:
                runs.append({"sign":state,"rows":[(i,row)]})
            else:
                runs[-1]["rows"].append((i,row))
        if not runs or p["terminal_sign"] is not None and runs[-1]["sign"]!=p["terminal_sign"]:
            continue
        n=len(p["signs"])
        sequences=[runs[i:i+n] for i in range(len(runs)-n+1)
                   if [r["sign"] for r in runs[i:i+n]]==p["signs"]]
        if p["selection"]=="last":
            sequences=sequences[-1:]
        for seq in sequences:
            nodes=[]
            for j,run in enumerate(seq,1):
                idx,row=run["rows"][0]
                nodes.append({"node_id":"state:"+str(j),"kind":"score_confirmation",
                              "actor":mapping[side],"score":row["score"],"sign":run["sign"],
                              "score_path_index":idx,"confirmation_t_sec":row["t_sec"],
                              "carrier_event_id":row.get("carrier_event_id"),
                              "state_path_indices":[i for i,_ in run["rows"]],
                              "previous_score_observed_t_sec":row.get("previous_score_observed_t_sec"),
                              "requires_goal_localization":not row.get("opening",False),
                              "media_window":None,"story_anchor":True})
            result.append({"candidate_id":template["template_id"]+":"+str(len(result)+1),
                           "subjects":[mapping[side]],"nodes":nodes,
                           "edges":[{"from":a["node_id"],"to":b["node_id"],
                                     "relation":"confirmed_score_state_transition",
                                     "causal_verified":False} for a,b in zip(nodes,nodes[1:])],
                           "narrative_goal":template["narrative_goal"],
                           "quality_verified":False,"first_live_verified":False,
                           "release_authorized":False})
    return result
