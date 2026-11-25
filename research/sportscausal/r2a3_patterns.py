"""Run R2a.3 from saved R1.1 semantics and full Stage 1.2 evidence.

No prior experiment is rerun. The three arms isolate chain and score input.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from pathlib import Path
from causal_episodes import PROJECTIONS, _actor, _episode, _union
from event_relation_graph import build_relation_graph
from episode_patterns import match_episodes, _diff
from template_graph import check, read, write


def project_graph(graph):
    by = {a["event_id"]: a for a in graph["atoms"]}
    parent = {eid:eid for eid in by}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in graph["edges"]:
        x,y = e["event_ids"]
        parent[root(y)] = root(x)
    components = defaultdict(list)
    component_edges = defaultdict(list)
    for a in by.values():
        components[root(a["event_id"])].append(a)
    for e in graph["edges"]:
        component_edges[root(e["event_ids"][0])].append(e)
    projected, diagnostics = [], []
    for r,rows in components.items():
        rows.sort(key=lambda a:(a["t"],a["event_id"]))
        links = component_edges[r]
        component_id = "attack:"+rows[0]["event_id"]
        for p in PROJECTIONS:
            groups = defaultdict(list)
            for a in rows:
                side = _actor(a,p)
                if side:
                    groups[side].append(a)
            # Preserve direct facts if a projection conflicts. Do not merge
            # opposing actors into the same story node.
            if len(groups)>1:
                diagnostics.append({"component_id":component_id,"predicate":p,"reason":"opposing_projection_roles"})
            for side,core in groups.items():
                if len(groups)>1:
                    for a in core:
                        ep = _episode(p,side,[a],[a["event_id"]],None)
                        ep["component_id"] = "isolated:"+a["event_id"]
                        projected.append(ep)
                else:
                    relation = {"kind":"typed_relation_path","edges":links,"causal_verified":False} if links else None
                    ep = _episode(p,side,rows,[a["event_id"] for a in core],relation)
                    ep["component_id"] = component_id
                    ep["predicate_evidence"] = [{"event_id":a["event_id"],**a["predicates"][p]} for a in core]
                    ep["goal_score_bindings"] = [a["goal_score_binding"] for a in rows if a.get("goal_score_binding")]
                    projected.append(ep)
    # Maintain the baseline same-side overlap proxy for standalone atoms. Do
    # not merge two distinct graph paths merely because clip windows overlap.
    grouped = defaultdict(list)
    for ep in projected:
        grouped[(ep["predicate"],ep["actor"])].append(ep)
    episodes = []
    for _,group in sorted(grouped.items()):
        merged=[]
        for ep in sorted(group,key=lambda e:(e["window"][0],e["anchor_t"],e["event_ids"])):
            if merged and ep["window"][0]<merged[-1]["window"][1]:
                old=merged[-1]
                if not old["relation"] and not ep["relation"]:
                    old["event_ids"]+=ep["event_ids"]
                    old["core_event_ids"]+=ep["core_event_ids"]
                    old["window"][1]=max(old["window"][1],ep["window"][1])
                    old["media_windows"]=_union(old["media_windows"]+ep["media_windows"])
                    old["anchor_t"]=min(old["anchor_t"],ep["anchor_t"])
                    old["score_observations"]+=ep["score_observations"]
                    old.setdefault("predicate_evidence",[]).extend(ep.get("predicate_evidence",[]))
                    old.setdefault("goal_score_bindings",[]).extend(ep.get("goal_score_bindings",[]))
                    old["component_id"]+="+"+ep["component_id"]
                    continue
                diagnostics.append({"reason":"overlapping_distinct_path_windows","predicate":ep["predicate"],
                                    "event_ids":[old["event_ids"],ep["event_ids"]]})
            merged.append(ep)
        episodes.extend(merged)
    episodes.sort(key=lambda e:(e["anchor_t"],e["predicate"],e["actor"],e["event_ids"]))
    for i,e in enumerate(episodes,1):
        e["episode_id"]="episode:"+str(i)
    return {"schema":"v3r_general_causal_episodes_v2","video_id":graph["video_id"],
            "input_tier":graph["input_tier"],"use_chains":graph["use_chains"],"episodes":episodes,
            "local_links":graph["edges"],"rejected_links":graph["rejected_edges"],
            "unresolved_relations":graph["unresolved_relations"],"inferred_roles":graph["inferred_roles"],
            "goal_bindings":graph["goal_bindings"],"projection_diagnostics":diagnostics,
            "quality_verified":False,"first_live_verified":False}


def run(evidence, semantics, score_doc, templates, out, *, max_action_gap_sec=5.0):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    bundles={}
    summary={"schema":"v3r_general_r2a3_ablation_v1","video_id":evidence["video_id"],
             "input_tier":evidence["input_tier"],"http_calls":0,"arms":{},"quality_verified":False}
    # Explicitly separate a score-path gain from a predicted-chain gain.
    for name,chains,score in (("full",True,score_doc),("without_chains",False,score_doc),
                              ("without_score",True,None)):
        e=evidence if chains else {**evidence,"chains":{}}
        graph=build_relation_graph(semantics,e,score,use_chains=chains,max_action_gap_sec=max_action_gap_sec)
        bundle=project_graph(graph)
        bundles[name]=bundle
        d=out/name
        d.mkdir()
        write(d/"relation_graph.json",graph)
        write(d/"causal_episodes.json",bundle)
        arm={"n_links":len(graph["edges"]),"n_role_inferences":len(graph["inferred_roles"]),
             "n_score_bound_goals":len(graph["goal_bindings"]["bindings"]),
             "n_unresolved_relations":len(graph["unresolved_relations"]),"patterns":{}}
        for t in templates:
            result=match_episodes(t,bundle)
            tid=t["template_id"]
            write(d/(tid+".json"),result)
            arm["patterns"][tid]={"n_predicate_episodes":result["n_predicate_episodes"],
                "candidates":[{"subjects":c["subjects"],"actor_runs":c["actor_runs"],
                               "event_ids":[n["event_ids"] for n in c["nodes"]]} for c in result["candidates"]]}
        summary["arms"][name]=arm
    for name in ("without_chains","without_score"):
        write(out/("diff_"+name+".json"),_diff(bundles["full"],bundles[name]))
    write(out/"summary.json",summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",required=True)
    p.add_argument("--semantics",required=True,help="R2a.2 normalized_semantics.json")
    p.add_argument("--score-path",required=True,help="Existing V3-R path plus explicit source and score-side mapping")
    p.add_argument("--out-dir",required=True)
    p.add_argument("--allow-dev",action="store_true")
    p.add_argument("--max-action-gap-sec",type=float,default=5.0)
    a=p.parse_args()
    e=read(a.evidence)
    check(a.allow_dev or e.get("input_tier") in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},"DEV authorization required")
    templates=[read(Path(__file__).parent/"patterns"/(name+".json"))
               for name in ("keeper_rescue","alternating_threats")]
    run(e,read(a.semantics),read(a.score_path),templates,a.out_dir,max_action_gap_sec=a.max_action_gap_sec)

if __name__=="__main__":
    main()
