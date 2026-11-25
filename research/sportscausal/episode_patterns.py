"""R2a.2: Repeat/Alternate over episode projections, with paired ablation.

The output is candidate anchors with evidence segments, not an EDL or a
claim about first-live footage. Run once on the unchanged Stage 1.2 input.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from episode_semantics import normalize_for_episodes
from causal_episodes import build_episodes, PROJECTIONS
from template_graph import check,read,write


def _runs(episodes):
    runs=[]
    for ep in episodes:
        if runs and runs[-1]["actor"]==ep["actor"]:
            runs[-1]["episodes"].append(ep)
        else:
            runs.append({"actor":ep["actor"],"episodes":[ep]})
    return runs

def match_episodes(template, bundle):
    check(all(k in template for k in ("template_id","category","subtype","narrative_goal","pattern")),
          "missing template fields")
    p=template["pattern"]
    check(isinstance(p,dict) and set(p)=={"operator","predicate","min_occurrences"}
          and p["operator"] in {"repeat","alternate"} and p["predicate"] in PROJECTIONS,
          "invalid episode pattern")
    check(type(p["min_occurrences"]) is int and p["min_occurrences"] >= (3 if p["operator"]=="alternate" else 2),
          "invalid occurrence minimum")
    episodes=[e for e in bundle["episodes"] if e["predicate"]==p["predicate"]]
    episodes.sort(key=lambda e:(e["anchor_t"],e["actor"],e["episode_id"]))
    raw=[]
    ambiguous=[]
    overlapping=[]
    if p["operator"]=="repeat":
        for side in sorted({e["actor"] for e in episodes}):
            eps=[e for e in episodes if e["actor"]==side]
            if len(eps)>=p["min_occurrences"]:
                raw.append(([side],eps,None))
    else:
        # Media windows can overlap even when annotated actions have distinct
        # times. Flag these overlaps; only equal action times lack an order.
        for i,a in enumerate(episodes):
            for b in episodes[i+1:]:
                if b["actor"]==a["actor"]:
                    continue
                if a["anchor_t"]==b["anchor_t"]:
                    ambiguous.extend([a["episode_id"],b["episode_id"]])
                if any(x<v and y>u for x,y in a["media_windows"] for u,v in b["media_windows"]):
                    overlapping.append([a["episode_id"],b["episode_id"]])
        eps=[e for e in episodes if e["episode_id"] not in set(ambiguous)]
        runs=_runs(eps)
        if len(runs)>=p["min_occurrences"]:
            raw.append((sorted({r["actor"] for r in runs}),eps,
                        [{"actor":r["actor"],"n_episodes":len(r["episodes"])} for r in runs]))
    candidates=[]
    for i,(sides,eps,runs) in enumerate(raw,1):
        nodes=[{"node_id":"anchor:"+str(j),**e,"story_anchor":True} for j,e in enumerate(eps,1)]
        candidates.append({"candidate_id":template["template_id"]+":"+str(i),
                           "subjects":sides,"actor_runs":runs,"nodes":nodes,
                           "edges":[{"from":a["node_id"],"to":b["node_id"],
                                     "relation":"temporal_episode_order","causal_verified":False}
                                    for a,b in zip(nodes,nodes[1:])],
                           "first_live_verified":False,"quality_verified":False,
                           "release_authorized":False})
    return {"schema":"v3r_general_episode_candidates_v1","video_id":bundle["video_id"],
            "template_id":template["template_id"],"input_tier":bundle["input_tier"],
            "category":template["category"],"subtype":template["subtype"],
            "narrative_goal":template["narrative_goal"],
            "use_chains":bundle["use_chains"],"n_predicate_episodes":len(episodes),
            "ambiguous_order_episode_ids":sorted(set(ambiguous)),
            "cross_actor_overlapping_media":overlapping,
            "candidates":candidates,"scope":"whole-match anchor discovery; no dominance or narrative quality claim",
            "first_live_verified":False,"quality_verified":False,"release_authorized":False}

def _signature(e):
    return (e["predicate"],e["actor"],tuple(sorted(e["event_ids"])))

def _diff(full,ablated):
    f={_signature(e):e for e in full["episodes"]}
    a={_signature(e):e for e in ablated["episodes"]}
    return {"with_chain_only":[f[k] for k in sorted(f.keys()-a.keys())],
            "without_chain_only":[a[k] for k in sorted(a.keys()-f.keys())],
            "n_unchanged_episode_memberships":len(f.keys() & a.keys()),
            "role_inferences":full["inferred_roles"],
            "local_links":full["local_links"],
            "n_rejected_local_links":len(full["rejected_links"])}

def run(evidence,templates,out,*,max_action_gap_sec=5.0):
    s=normalize_for_episodes(evidence)
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    write(out/"normalized_semantics.json",s)
    full=build_episodes(s,evidence,use_chains=True,max_action_gap_sec=max_action_gap_sec)
    # Remove the chain input physically, in addition to disabling its use.
    no_chain={**evidence,"chains":{}}
    ablated=build_episodes(s,no_chain,use_chains=False,max_action_gap_sec=max_action_gap_sec)
    diff=_diff(full,ablated)
    summary={"schema":"v3r_general_r2a2_ablation_v1","video_id":evidence["video_id"],
             "input_tier":evidence["input_tier"],"http_calls":0,
             "n_local_links":len(full["local_links"]),
             "n_inferred_roles":len(full["inferred_roles"]),
             "n_with_chain_only":len(diff["with_chain_only"]),
             "n_without_chain_only":len(diff["without_chain_only"]),
             "patterns":{},"quality_verified":False,"first_live_verified":False}
    for name,bundle in (("with_chains",full),("without_chains",ablated)):
        d=out/name
        d.mkdir()
        write(d/"causal_episodes.json",bundle)
        for t in templates:
            r=match_episodes(t,bundle)
            tid=t["template_id"]
            write(d/(tid+".json"),r)
            summary["patterns"].setdefault(tid,{})[name]={
                "n_predicate_episodes":r["n_predicate_episodes"],
                "candidates":[{"subjects":c["subjects"],"n_episodes":len(c["nodes"]),
                               "actor_runs":c["actor_runs"],
                               "event_ids":[n["event_ids"] for n in c["nodes"]]}
                              for c in r["candidates"]]}
    write(out/"ablation_diff.json",diff)
    write(out/"summary.json",summary)
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",required=True)
    p.add_argument("--out-dir",required=True)
    p.add_argument("--allow-dev",action="store_true")
    p.add_argument("--max-action-gap-sec",type=float,default=5.0)
    a=p.parse_args()
    e=read(a.evidence)
    check(a.allow_dev or e.get("input_tier") in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires --allow-dev")
    templates=[read(Path(__file__).parent/"patterns"/(name+".json"))
               for name in ("keeper_rescue","alternating_threats")]
    run(e,templates,a.out_dir,max_action_gap_sec=a.max_action_gap_sec)
if __name__=="__main__":
    main()
