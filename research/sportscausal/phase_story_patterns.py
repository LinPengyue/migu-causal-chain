"""R2c: phase-change hypotheses from successive sustained episode runs.

Observed threat runs are sparse evidence, not possession/dominance statistics.
A switch interval is a search region, never an executable clip.
"""
from copy import deepcopy
from template_graph import check

def phase_candidates(template,bundle):
    p=template["pattern"]
    check(p["operator"]=="phase_change" and p["predicate"]=="attacking_threat",
          "unsupported phase observable")
    minimum=p["min_episodes_per_phase"]
    check(type(minimum) is int and minimum>=2,"at least two independent episodes per phase")
    eps=sorted([e for e in bundle["episodes"] if e["predicate"]==p["predicate"]
                and e["actor_role"]=="attacking_team"],key=lambda e:(e["anchor_t"],e["episode_id"]))
    # Never choose between coincident/overlapping opposite-side evidence.
    # Ambiguity splits a run rather than connecting phases across it.
    ambiguous=set()
    for i,a in enumerate(eps):
        for b in eps[i+1:]:
            if a["actor"]==b["actor"]:
                continue
            if a["anchor_t"]==b["anchor_t"] or any(x<v and y>u for x,y in a["media_windows"]
                                                   for u,v in b["media_windows"]):
                ambiguous.update([a["episode_id"],b["episode_id"]])
    blocks=[]; runs=[]
    for ep in eps:
        if ep["episode_id"] in ambiguous:
            if runs:
                blocks.append(runs)
                runs=[]
            continue
        if not runs or runs[-1][0]["actor"]!=ep["actor"]:
            runs.append([])
        # Count distinct physical components only.
        seen={eid for old in runs[-1] for eid in old["event_ids"]}
        if seen.intersection(ep["event_ids"]) or any(old["component_id"]==ep["component_id"] for old in runs[-1]):
            continue
        runs[-1].append(ep)
    if runs:
        blocks.append(runs)
    result=[]
    for runs in blocks:
        for a,b in zip(runs,runs[1:]):
            if len(a)<minimum or len(b)<minimum:
                continue
            left=max(w[1] for ep in a for w in ep["media_windows"])
            right=min(w[0] for ep in b for w in ep["media_windows"])
            if left>right:
                continue
            nodes=[]
            for phase,group in enumerate((a,b),1):
                for ep in group:
                    nodes.append({**deepcopy(ep),"node_id":"phase:"+str(phase)+":"+ep["episode_id"],
                                  "kind":"phase_episode","phase_index":phase,"story_anchor":True})
            related=[{"event_ids":e["event_ids"],"score_beneficiary":e["actor"],
                      "anchor_t":e["anchor_t"],"episode_id":e["episode_id"]}
                     for e in bundle["episodes"] if e["predicate"]=="scoring_outcome" and
                     left<=e["anchor_t"]<=right]
            result.append({"candidate_id":template["template_id"]+":"+str(len(result)+1),
                "subjects":[a[0]["actor"],b[0]["actor"]],"nodes":nodes,
                "edges":[{"from":x["node_id"],"to":y["node_id"],
                          "relation":"observed_phase_switch" if x["phase_index"]!=y["phase_index"] else
                                     "within_observed_threat_run","causal_verified":False}
                         for x,y in zip(nodes,nodes[1:])],
                "phases":[{"actor":group[0]["actor"],"episode_ids":[e["episode_id"] for e in group],
                           "n_observed_episodes":len(group),
                           "observed_interval":[group[0]["anchor_t"],group[-1]["anchor_t"]]}
                          for group in (a,b)],
                "switch_search_interval":[left,right],"score_context":related,
                "phase_semantics":"observed_sustained_threat_run_change_not_dominance",
                "quality_verified":False,"first_live_verified":False,"release_authorized":False})
    return {"candidates":result,"ambiguous_episode_ids":sorted(ambiguous),
            "n_observed_episodes":len(eps),"min_episodes_per_phase":minimum}
