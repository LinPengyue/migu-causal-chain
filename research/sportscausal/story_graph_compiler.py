"""R3.1: compile frozen R2 candidates into a common narrative graph.

No model calls, new recognition, candidate ranking or causal certification.
Source IDs remain traceable and story-local; same footage can occur in
different stories, but never needs to be duplicated within one draft.
"""
from copy import deepcopy
from template_graph import check

def _refs(n):
    return sorted(set(n.get("observation_task_ids",[])))

def compile_story(result,candidate,operator,task_index):
    template=result.get("template") or {k:result[k] for k in
        ("template_id","category","subtype","narrative_goal")}
    c=deepcopy(candidate)
    nodes=[]; edges=[]; context=[]; diagnostics=[]
    for n in c["nodes"]:
        ids=n["event_ids"]
        kind="missing" if n.get("localization_status")=="missing_action" else (
             "transition" if n.get("localization_status")=="opening_state_only" else "anchor")
        check(kind!="missing" or not ids and not n.get("media_windows"),"missing node has fabricated media")
        check(kind!="anchor" or bool(ids),"empty anchor")
        node={**n,"node_type":kind,"source_node_id":n["node_id"],
              "required":kind in {"anchor","missing"},"material_ids":[],
              "observation_task_ids":_refs(n)}
        nodes.append(node)
        if kind=="missing":
            diagnostics.append({"kind":"missing_required_action","node_id":n["node_id"],
                                "observation_task_ids":_refs(n)})
    node_ids={n["node_id"] for n in nodes}
    check(len(node_ids)==len(nodes),"duplicate story node")
    for e in c["edges"]:
        check(e["from"] in node_ids and e["to"] in node_ids,"unbound edge")
        edges.append({**e,"edge_type":e["relation"],"causal_verified":False})
    # Context candidates keep both semantic perspectives, but are not
    # selected into the initial EDL. Physical dedup is done downstream.
    for gap in c.get("interval_context",[]):
        check(gap["from"] in node_ids and gap["to"] in node_ids,"unbound context gap")
        for ep in gap["context_candidates"]:
            context.append({**ep,"context_role":"inter_anchor","from":gap["from"],"to":gap["to"]})
        if not gap["context_candidates"]:
            diagnostics.append({"kind":"empty_inter_anchor_context","from":gap["from"],"to":gap["to"],
                                "search_interval":gap.get("certain_interior")})
    for ep in c.get("post_last_anchor_context_candidates",[]):
        context.append({**ep,"context_role":"post_anchor","from":nodes[-1]["node_id"],"to":None})
    if operator=="state_transition":
        diagnostics.append({"kind":"terminal_score_not_final_whistle",
                            "basis":c.get("terminal_basis")})
    if template["template_id"]=="lead_preservation":
        diagnostics.append({"kind":"lead_signature_requires_post_lead_defensive_evidence",
                            "note":"level-to-lead alone does not establish preservation"})
    if operator=="phase_change":
        diagnostics.append({"kind":"sparse_phase_hypothesis","phases":c["phases"],
                            "search_interval":c["switch_search_interval"]})
        switch={"node_id":"phase_switch","node_type":"transition","source_node_id":None,
                "event_ids":[],"media_windows":[],"required":False,"material_ids":[],
                "search_interval":c["switch_search_interval"],
                "observation_task_ids":_refs(c)}
        # Explicit transition is semantic only, never a clip.
        nodes.append(switch)
        before=[n for n in nodes if n.get("phase_index")==1][-1]
        after=[n for n in nodes if n.get("phase_index")==2][0]
        edges.extend([{"from":before["node_id"],"to":"phase_switch","edge_type":"transition_hypothesis",
                       "causal_verified":False},
                      {"from":"phase_switch","to":after["node_id"],"edge_type":"transition_hypothesis",
                       "causal_verified":False}])
    paths=c.get("path_alternatives",[])
    if operator=="relation_path":
        check(bool(paths),"relation candidate missing path")
        # Single path: materialize all available intermediate members.
        # Multiple paths: keep only common members in their shared order,
        # leave alternative-specific membership for Planner/Verifier.
        common=set(paths[0]["event_ids"])
        for p in paths[1:]:
            common.intersection_update(p["event_ids"])
        anchors={eid for n in nodes for eid in n["event_ids"]}
        middle=[eid for eid in paths[0]["event_ids"] if eid in common and eid not in anchors]
        if middle:
            nodes.insert(1,{"node_id":"path_context","node_type":"context","source_node_id":None,
                 "event_ids":middle,"media_windows":[],"required":True,"material_ids":[],
                 "context_role":"path_intermediate","observation_task_ids":_refs(c)})
            edges.extend([{"from":nodes[0]["node_id"],"to":"path_context",
                          "edge_type":"predicted_path_context","causal_verified":False},
                         {"from":"path_context","to":nodes[-1]["node_id"],
                          "edge_type":"predicted_path_context","causal_verified":False}])
        if len(paths)>1:
            diagnostics.append({"kind":"alternative_path_selection_pending","n_alternatives":len(paths)})
        diagnostics.append({"kind":"path_continuity_unverified","n_alternatives":len(paths)})
    direct=set(_refs(c))
    for n in nodes:
        direct.update(n["observation_task_ids"])
    check(direct<=set(task_index),"unknown linked observation task")
    # Keep the full original candidate as provenance; don't flatten role fields.
    return {"schema":"sportscausal_story_graph_v1","video_id":result["video_id"],
            "input_tier":result["input_tier"],"story_id":c["candidate_id"],
            "template_id":template["template_id"],"category":template["category"],
            "subtype":template["subtype"],"narrative_goal":template["narrative_goal"],
            "operator":operator,"subjects":c["subjects"],"nodes":nodes,"edges":edges,
            "context_candidates":context,"path_alternatives":deepcopy(paths),
            "direct_observation_task_ids":sorted(direct),"source_candidate":c,
            "strict_threat_metric_eligible":result.get("strict_threat_metric_eligible",True),
            "diagnostics":diagnostics,"quality_verified":False,
            "first_live_verified":False,"release_authorized":False}
