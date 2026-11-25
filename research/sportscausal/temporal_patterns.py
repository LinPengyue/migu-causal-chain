"""V3-R-General R2a: two composable temporal patterns.

Repeat: group by explicitly bound actor, then distinct evidence windows.
Alternate: group consecutive actor runs; require repeated changes, not one switch.
The output is a set of candidate anchor graphs, not a finished edit.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from template_graph import check, read, write
from semantic_normalization import normalize

PREDICATES={"goalkeeper_rescue","attacking_threat"}

def validate_pattern(t):
    for key in ("template_id","category","subtype","narrative_goal","pattern"):
        check(key in t,"missing "+key)
    p=t["pattern"]
    check(isinstance(p,dict) and set(p)=={"operator","predicate","min_occurrences"},"invalid pattern schema")
    check(p["operator"] in {"repeat","alternate"},"unsupported operator")
    check(p["predicate"] in PREDICATES,"unsupported predicate")
    lo=p["min_occurrences"]
    check(type(lo) is int and lo >= (3 if p["operator"]=="alternate" else 2),"invalid minimum")
    return p

def episodes(rows,predicate):
    """Conservative distinct-window proxy, not possession segmentation."""
    groups=[]
    for a in sorted(rows,key=lambda x:(x["window"][0],x["window"][1],x["t"],x["event_id"])):
        side=a["predicates"][predicate]["actor"]
        lo,hi=a["window"]
        # Only merge overlapping windows of the same actor. Adjacent windows
        # are not necessarily one attack. Never fill a temporal gap.
        if groups and groups[-1]["actor"]==side and lo < groups[-1]["window"][1]:
            g=groups[-1]
            g["window"][1]=max(g["window"][1],hi)
            g["anchor_t"]=min(g["anchor_t"],a["t"])
            g["event_ids"].append(a["event_id"])
        else:
            groups.append({"actor":side,"window":[lo,hi],"anchor_t":a["t"],"event_ids":[a["event_id"]]})
    return sorted(groups,key=lambda g:(g["anchor_t"],g["window"][0],g["actor"]))

def _repeat(rows,p):
    result=[]
    for side in sorted({a["predicates"][p["predicate"]]["actor"] for a in rows}):
        eps=episodes([a for a in rows if a["predicates"][p["predicate"]]["actor"]==side],p["predicate"])
        if len(eps)>=p["min_occurrences"]:
            result.append({"subjects":[side],"episodes":eps})
    return result

def _alternate(rows,p):
    # Merge same-side overlapping annotations before finding actor runs.
    eps=[]
    for side in sorted({a["predicates"][p["predicate"]]["actor"] for a in rows}):
        eps.extend(episodes([a for a in rows if a["predicates"][p["predicate"]]["actor"]==side],p["predicate"]))
    eps.sort(key=lambda e:(e["anchor_t"],e["actor"]))
    # Simultaneous opposite actor anchors are ambiguous order. Preserve them
    # in diagnostics; they cannot manufacture an alternation.
    by_time={}
    for e in eps:
        by_time.setdefault(e["anchor_t"],set()).add(e["actor"])
    runs=[]
    for e in eps:
        if len(by_time[e["anchor_t"]])>1:
            continue
        if runs and runs[-1]["actor"]==e["actor"]:
            runs[-1]["episodes"].append(e)
        else:
            runs.append({"actor":e["actor"],"episodes":[e]})
    if len(runs)<p["min_occurrences"]:
        return []
    return [{"subjects":sorted({r["actor"] for r in runs}),
             "episodes":[e for r in runs for e in r["episodes"]],
             "actor_runs":[{"actor":r["actor"],"n_episodes":len(r["episodes"])} for r in runs]}]

def match(t,semantics,evidence):
    p=validate_pattern(t)
    check(semantics["video_id"]==evidence["video_id"],"source mismatch")
    rows=[a for a in semantics["atoms"] if p["predicate"] in a["predicates"]]
    raw=(_repeat if p["operator"]=="repeat" else _alternate)(rows,p)
    index={}
    for c in evidence["chains"].values():
        if c["state"] not in {"FULL","PARTIAL"}:
            continue
        for eid in c["available_event_ids"]:
            index.setdefault(eid,[]).append(c["chain_id"])
    candidates=[]
    for i,r in enumerate(raw,1):
        nodes=[]
        for j,e in enumerate(r["episodes"],1):
            refs=sorted({cid for eid in e["event_ids"] for cid in index.get(eid,[])})
            nodes.append({"node_id":f"anchor:{j}",**e,"predicate":p["predicate"],
                          "chain_context_ids":refs,"story_anchor":True})
        edges=[{"from":a["node_id"],"to":b["node_id"],"relation":"temporal_anchor_order",
                "causal_verified":False} for a,b in zip(nodes,nodes[1:])]
        candidates.append({"candidate_id":f"{t['template_id']}:{i}","subjects":r["subjects"],
                           "actor_runs":r.get("actor_runs"),"nodes":nodes,"edges":edges,
                           "narrative_goal":t["narrative_goal"],"quality_verified":False,
                           "first_live_verified":False,"release_authorized":False})
    return {"schema":"v3r_general_anchor_candidates_v1","template_id":t["template_id"],
            "category":t["category"],"subtype":t["subtype"],"input_tier":evidence["input_tier"],
            "video_id":evidence["video_id"],"n_predicate_events":len(rows),"candidates":candidates,
            "scope":"anchor discovery only; chain membership is contextual, not verified causal linkage",
            "episode_limit":"same actor overlapping media windows are a conservative distinct-episode proxy",
            "alternation_limit":"actor runs of observed threat proxies, not established dominance or possession",
            "first_live_verified":False,"quality_verified":False,"release_authorized":False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",required=True)
    p.add_argument("--template",required=True)
    p.add_argument("--out-dir",required=True)
    p.add_argument("--allow-dev",action="store_true")
    a=p.parse_args()
    e=read(a.evidence)
    check(a.allow_dev or e.get("input_tier") in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires --allow-dev")
    t=read(a.template)
    s=normalize(e)
    r=match(t,s,e)
    out=Path(a.out_dir)
    out.mkdir(parents=True,exist_ok=False)
    write(out/"normalized_semantics.json",s)
    write(out/"anchor_candidates.json",r)

if __name__=="__main__":
    main()
