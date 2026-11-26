"""R2a.4 candidate views and observation handoff; no old ablation rerun."""
from __future__ import annotations
import argparse
from copy import deepcopy
from pathlib import Path
from collections import Counter
from causal_episodes import _episode, _union
from r2a3_patterns import project_graph
from episode_patterns import match_episodes
from r2a4_relation_graph import build_role_graph
from template_graph import check, read, write

def project_roles(graph):
    bundle=project_graph(graph)
    by={a["event_id"]:a for a in graph["atoms"]}
    for ep in bundle["episodes"]:
        ep["actor_role"]="goalkeeper_team" if ep["predicate"].startswith("goalkeeper") else "attacking_team"
        ep["goal_roles"]=[by[e]["goal_roles"] for e in ep["event_ids"] if by[e].get("goal_roles")]
    context={e["event_ids"][-1]:e for e in graph["outcome_context_edges"]}
    for b in graph["goal_bindings"]["bindings"]:
        eid=b["event_id"]
        link=context.get(eid)
        ids=link["event_ids"] if link else [eid]
        ep=_episode("scoring_outcome",b["score_beneficiary"],[by[x] for x in ids],[eid],link)
        ep.update(episode_id="score_outcome:"+str(b["path_index"]),component_id="score:"+eid,
                  actor_role="score_beneficiary",goal_roles=[by[eid]["goal_roles"]],
                  goal_score_bindings=[b],context_event_ids=[x for x in ids if x!=eid],
                  distinct_episode_basis="score_bound_goal_action_candidate")
        bundle["episodes"].append(ep)
    bundle["episodes"].sort(key=lambda e:(e["anchor_t"],e["predicate"],e["actor"],e["episode_id"]))
    bundle.update(schema="v3r_general_role_episodes_v1",observation_tasks=graph["observation_tasks"],
                  outcome_context_edges=graph["outcome_context_edges"])
    return bundle

def match_mixed_alternation(template,bundle):
    """Separate hypothesis view; never report it as strict alternating threat."""
    episodes=deepcopy([e for e in bundle["episodes"] if e["predicate"]=="attacking_threat"])
    standalone=[]
    outcomes=[e for e in bundle["episodes"] if e["predicate"]=="scoring_outcome"]
    for outcome in outcomes:
        hits=[e for e in episodes if set(e["event_ids"]) & set(outcome["event_ids"])]
        if len(hits)==1:
            # A goal and its independent attack anchor need not be counted
            # twice. Keep the score role distinct, even when sides disagree.
            hits[0].setdefault("related_score_outcomes",[]).append(deepcopy(outcome))
        elif len(hits)>1:
            # Preserve the complete score outcome outside the alternation
            # sequence instead of duplicating a possibly shared attack.
            standalone.append(deepcopy(outcome))
        else:
            episodes.append(deepcopy(outcome))
    for ep in episodes:
        ep["original_predicate"]=ep["predicate"]
        ep["predicate"]="attacking_threat"  # matching adapter only
    temp={**bundle,"episodes":episodes}
    t={**template,"template_id":template["template_id"]+"_score_context",
       "subtype":"攻防与比分交替（待视频核验）",
       "narrative_goal":["组织攻防证据与比分变化的叙事假设；比分受益方不代表进攻方"]}
    result=match_episodes(t,temp)
    for c in result["candidates"]:
        c["subject_roles"]=sorted({(n["actor"],n["actor_role"]) for n in c["nodes"]})
        c["subject_roles"]=[{"team":s,"role":r} for s,r in c["subject_roles"]]
        for n in c["nodes"]:
            n["predicate"]=n.pop("original_predicate")
        # The run count here is a mixed role timeline, not an attack count.
        c["mixed_role_runs"]=c.pop("actor_runs")
    result["n_mixed_episodes"]=result.pop("n_predicate_episodes")
    result["scope"]="mixed_score_and_attack_narrative_hypothesis_not_alternating_threat_result"
    result["unassigned_score_outcomes"]=standalone
    result["strict_threat_metric_eligible"]=False
    return result

def run(evidence,semantics,score_doc,templates,out,*,base_graph=None,max_action_gap_sec=5.0):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    graph=build_role_graph(semantics,evidence,score_doc,base_graph=base_graph,
                           max_action_gap_sec=max_action_gap_sec)
    bundle=project_roles(graph)
    write(out/"relation_graph.json",graph)
    write(out/"causal_episodes.json",bundle)
    write(out/"observation_tasks.json",{"schema":"sportscausal_observation_tasks_v1",
          "video_id":graph["video_id"],"tasks":graph["observation_tasks"],"http_calls":0})
    write(out/"scoring_outcomes.json",{"video_id":graph["video_id"],
          "episodes":[e for e in bundle["episodes"] if e["predicate"]=="scoring_outcome"],
          "unlocalized_score_transitions":graph["goal_bindings"]["unresolved"]})
    summary={"schema":"v3r_general_r2a4_roles_v1","video_id":graph["video_id"],
             "input_tier":graph["input_tier"],"http_calls":0,
             "reused_without_score_graph":graph["reused_without_score_graph"],
             "n_attack_save_links":len(graph["edges"]),
             "n_score_bound_goals":len(graph["goal_bindings"]["bindings"]),
             "n_goal_context_edges":len(graph["outcome_context_edges"]),
             "n_role_inferences":len(graph["inferred_roles"]),
             "n_score_derived_executor_or_shooter_inferences":sum(
                 bool(x.get("score_binding")) for x in graph["inferred_roles"]),
             "goal_roles":graph["goal_role_claims"],
             "observation_tasks_by_type":dict(Counter(t["task_type"] for t in graph["observation_tasks"])),
             "patterns":{},"quality_verified":False,"first_live_verified":False}
    for template in templates:
        result=match_episodes(template,bundle)
        tid=template["template_id"]
        write(out/(tid+".json"),result)
        summary["patterns"][tid]={"n_predicate_episodes":result["n_predicate_episodes"],
            "candidates":[{"subjects":c["subjects"],"actor_runs":c["actor_runs"],
                           "event_ids":[n["event_ids"] for n in c["nodes"]]} for c in result["candidates"]]}
        if template["pattern"]["operator"]=="alternate" and template["pattern"]["predicate"]=="attacking_threat":
            mixed=match_mixed_alternation(template,bundle)
            write(out/(mixed["template_id"]+".json"),mixed)
            summary["patterns"][mixed["template_id"]]={"n_mixed_episodes":mixed["n_mixed_episodes"],
                "strict_threat_metric_eligible":False,
                "candidates":[{"subjects":c["subjects"],"mixed_role_runs":c["mixed_role_runs"],
                    "nodes":[{"event_ids":n["event_ids"],"actor":n["actor"],
                              "actor_role":n["actor_role"],"predicate":n["predicate"]}
                             for n in c["nodes"]]} for c in mixed["candidates"]]}
    write(out/"summary.json",summary)
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",required=True)
    p.add_argument("--semantics",required=True)
    p.add_argument("--score-path",required=True)
    p.add_argument("--base-graph",help="Saved R2a.3 without_score/relation_graph.json (optional)")
    p.add_argument("--out-dir",required=True)
    p.add_argument("--allow-dev",action="store_true")
    p.add_argument("--max-action-gap-sec",type=float,default=5.0)
    a=p.parse_args()
    e=read(a.evidence)
    check(a.allow_dev or e.get("input_tier") in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},"DEV authorization required")
    templates=[read(Path(__file__).parent/"patterns"/(n+".json")) for n in ("keeper_rescue","alternating_threats")]
    run(e,read(a.semantics),read(a.score_path),templates,a.out_dir,
        base_graph=read(a.base_graph) if a.base_graph else None,max_action_gap_sec=a.max_action_gap_sec)

if __name__=="__main__":
    main()
