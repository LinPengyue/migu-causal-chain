"""V3-R-General R2: declarative temporal anchor discovery.

Repeat: group by explicitly bound actor, then distinct evidence windows.
Alternate: group consecutive actor runs; require repeated changes, not one switch.
The output is a set of candidate anchor graphs, not a finished edit.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from template_graph import check, read, write
from semantic_normalization import normalize
from score_state_patterns import validate_state_pattern, match_score_states

PREDICATES={"goalkeeper_rescue","attacking_threat","set_piece_execution","goal_action"}

def validate_pattern(t):
    for key in ("template_id","category","subtype","narrative_goal","pattern"):
        check(key in t,"missing "+key)
    p=t["pattern"]
    check(isinstance(p,dict),"invalid pattern schema")
    if p.get("operator")=="state_transition":
        return validate_state_pattern(p)
    if p.get("operator")=="relation_path":
        check(set(p)=={"operator","start_predicate","end_predicate","chain_subtypes"},"invalid relation path schema")
        check(p["start_predicate"] in PREDICATES and p["end_predicate"] in PREDICATES,"unsupported path predicate")
        check(isinstance(p["chain_subtypes"],list) and p["chain_subtypes"] and
              all(isinstance(x,str) and x for x in p["chain_subtypes"]),"explicit allowed prediction subtypes required")
        return p
    check(set(p)=={"operator","predicate","min_occurrences"},"invalid pattern schema")
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

def _relation_path(atoms,p,evidence):
    """Ordered, same-actor endpoint pairs in one complete predicted chain.

    FULL is a membership-availability assertion, not causal correctness.
    Never pair endpoints by proximity alone or complete PARTIAL chains.
    The caller supplies the prediction subtype vocabulary in the template.
    Keep all distinct supported pairs, rather than preferring a longer cut.
    """
    by_id={a["event_id"]:a for a in atoms}
    pairs={}
    for c in evidence["chains"].values():
        if c["state"]!="FULL" or c.get("subtype") not in p["chain_subtypes"]:
            continue
        ids=c["available_event_ids"]
        if not ids or len(ids)!=len(set(ids)) or any(i not in by_id for i in ids):
            continue
        members=[by_id[i] for i in ids]
        for j,end in enumerate(members):
            outcome=end["predicates"].get(p["end_predicate"])
            if not outcome:
                continue
            # Choose the last *explicitly* executed restart/action in the
            # predicted member order before the outcome. An intervening
            # opposing start or another outcome breaks this association.
            for start in reversed(members[:j]):
                if p["end_predicate"] in start["predicates"]:
                    break
                first=start["predicates"].get(p["start_predicate"])
                if not first:
                    continue
                if first["actor"]==outcome["actor"] and start["t"]<end["t"]:
                    key=(start["event_id"],end["event_id"])
                    if key not in pairs:
                        pairs[key]={"subjects":[first["actor"]],"episodes":[
                            {"actor":first["actor"],"window":start["window"],"anchor_t":start["t"],
                             "event_ids":[start["event_id"]],"predicate":p["start_predicate"]},
                            {"actor":outcome["actor"],"window":end["window"],"anchor_t":end["t"],
                             "event_ids":[end["event_id"]],"predicate":p["end_predicate"]}],
                            "path_chain_ids":[]}
                    pairs[key]["path_chain_ids"].append(c["chain_id"])
                break
    return sorted(pairs.values(),key=lambda r:(r["episodes"][0]["anchor_t"],r["episodes"][1]["anchor_t"],r["subjects"]))

def match(t,semantics,evidence,score_doc=None):
    p=validate_pattern(t)
    check(semantics["video_id"]==evidence["video_id"],"source mismatch")
    if p["operator"]=="state_transition":
        check(isinstance(score_doc,dict),"state transition requires an existing V3-R score path")
        return {"schema":"v3r_general_anchor_candidates_v1","template_id":t["template_id"],
                "category":t["category"],"subtype":t["subtype"],"input_tier":evidence["input_tier"],
                "video_id":evidence["video_id"],"n_predicate_events":len(score_doc.get("score_path",[])),
                "candidates":match_score_states(t,score_doc,evidence["video_id"]),
                "scope":"confirmed scoreboard states only; goal action localization must reuse V3-R",
                "first_live_verified":False,"quality_verified":False,"release_authorized":False}
    if p["operator"]=="relation_path":
        rows=[a for a in semantics["atoms"] if any(k in a["predicates"] for k in (p["start_predicate"],p["end_predicate"]))]
        raw=_relation_path(semantics["atoms"],p,evidence)
    else:
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
            nodes.append({"node_id":f"anchor:{j}",**e,"predicate":e.get("predicate",p.get("predicate")),
                          "chain_context_ids":refs,"story_anchor":True})
        edges=[{"from":a["node_id"],"to":b["node_id"],"relation":"temporal_anchor_order",
                "causal_verified":False} for a,b in zip(nodes,nodes[1:])]
        if r.get("path_chain_ids"):
            for edge in edges:
                edge["relation"]="predicted_chain_path_hypothesis"
                edge["path_chain_ids"]=sorted(set(r["path_chain_ids"]))
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
    p.add_argument("--score-path",help="Existing V3-R score path with explicit source/side mapping")
    a=p.parse_args()
    e=read(a.evidence)
    check(a.allow_dev or e.get("input_tier") in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires --allow-dev")
    t=read(a.template)
    s=normalize(e)
    r=match(t,s,e,read(a.score_path) if a.score_path else None)
    out=Path(a.out_dir)
    out.mkdir(parents=True,exist_ok=False)
    write(out/"normalized_semantics.json",s)
    write(out/"anchor_candidates.json",r)

if __name__=="__main__":
    main()
