"""R3.2/3.3: source-bound physical materials and an anchor-first preview EDL.

Merge overlapping/touching atomic windows only. Never fill a gap, use a
score confirmation/search interval as media, or certify first live.
"""
from copy import deepcopy
from template_graph import check, number

def _source_atom(evidence,eid):
    a=evidence["atoms"].get(eid)
    check(a is not None and a.get("event_id")==eid,"unknown atom "+str(eid))
    check(a.get("broadcast_phase")=="LIVE","non-live atom "+eid)
    w=a.get("window")
    check(isinstance(w,list) and len(w)==2 and all(number(x) for x in w)
          and 0<=w[0]<w[1]<=evidence["duration_sec"],"invalid source window "+eid)
    check(number(a.get("t")) and w[0]<=a["t"]<=w[1],"invalid action time "+eid)
    return a

def windows_for(evidence,ids):
    atoms=[_source_atom(evidence,eid) for eid in sorted(set(ids))]
    groups=[]
    for a in sorted(atoms,key=lambda x:(x["window"][0],x["window"][1],x["t"],x["event_id"])):
        lo,hi=a["window"]
        if groups and lo<=groups[-1]["window"][1]:
            groups[-1]["window"][1]=max(groups[-1]["window"][1],hi)
            groups[-1]["event_ids"].append(a["event_id"])
        else:
            groups.append({"window":[lo,hi],"event_ids":[a["event_id"]]})
    return groups

def _chain_refs(evidence,ids):
    ids=set(ids)
    return sorted(cid for cid,c in evidence["chains"].items() if c["state"] in {"FULL","PARTIAL"}
                  and ids.intersection(c["available_event_ids"]))

def _validate_declared_windows(evidence,node):
    ids=node["event_ids"]
    if not ids:
        check(not node.get("media_windows"),"unbound media windows")
        return
    expected=[g["window"] for g in windows_for(evidence,ids)]
    # Intermediate path nodes have no precomputed window, rebuilt from IDs.
    if node.get("media_windows"):
        check(node["media_windows"]==expected,"upstream window mismatch: "+str(node.get("node_id")))

def materialize(graph,evidence,task_index):
    check(graph["video_id"]==evidence["video_id"] and graph["input_tier"]==evidence["input_tier"],
          "material source mismatch")
    g=deepcopy(graph)
    nodes=g["nodes"]
    used=set()
    for n in nodes:
        _validate_declared_windows(evidence,n)
        if n["required"] and n["event_ids"]:
            used.update(n["event_ids"])
    # Candidate-specific windows and roles are rebuilt, not trusted from a
    # model or from a large interval. Source chronology defines the draft.
    groups=windows_for(evidence,used)
    materials=[]; edl=[]
    for i,group in enumerate(groups,1):
        ids=group["event_ids"]; lo,hi=group["window"]; mid="material:"+str(i)
        ns=[n for n in nodes if set(ids).intersection(n["event_ids"])]
        for n in ns:
            n["material_ids"].append(mid)
        refs=_chain_refs(evidence,ids)
        row={"material_id":mid,"video_id":evidence["video_id"],"event_ids":ids,
             "media_window":[lo,hi],"story_node_ids":[n["node_id"] for n in ns],
             "short_chain_ids":refs,"window_basis":"union_of_source_atomic_windows",
             "first_live_verified":False,"causal_verified":False}
        materials.append(row)
        edl.append({"segment_id":"seg:"+str(i),"source_material_id":mid,
                    "video_id":evidence["video_id"],"media_in":lo,"media_out":hi,
                    "event_ids":ids,"short_chain_ids":refs,
                    "story_node_ids":row["story_node_ids"],
                    "story_anchor":any(n["node_type"]=="anchor" for n in ns),
                    "include_in_cut":True,"edl_index":i,"narrative_order":i,
                    "time_provenance":{"basis":"union_of_source_atomic_windows"},
                    "verification_status":"draft","first_live_status":"NOT_VERIFIED",
                    "first_live_verified":False,"preview_only":True})
    # Distinct story nodes can share footage; keep all roles in the graph.
    # Avoid merging disjoint context episodes merely because their spans
    # overlap. Equal physical event membership shares one context record.
    pool={}
    for c in g["context_candidates"]:
        _validate_declared_windows(evidence,c)
        ids=sorted(set(c["event_ids"]))
        if not ids:
            continue
        key=tuple(ids)
        if key not in pool:
            pool[key]={"event_ids":ids,"media_windows":[x["window"] for x in windows_for(evidence,ids)],
                       "short_chain_ids":_chain_refs(evidence,ids),"perspectives":[],
                       "already_selected_event_ids":sorted(set(ids)&used),
                       "selected":False,"first_live_verified":False}
        pool[key]["perspectives"].append({k:deepcopy(c.get(k)) for k in
            ("episode_id","predicate","actor","actor_role","context_role","from","to")})
    context_pool=list(pool.values())
    for i,c in enumerate(context_pool,1):
        c["context_id"]="context:"+str(i)
        c["fully_covered_by_anchor_edl"]=set(c["event_ids"])<=used
        c["overlaps_anchor_media"]=any(x<v and y>u for x,y in c["media_windows"]
                                     for u,v in [m["media_window"] for m in materials])
    # Alternative paths stay in the graph; validate every referenced member.
    for alt in g["path_alternatives"]:
        _validate_declared_windows(evidence,alt)
    task_ids=set(g["direct_observation_task_ids"])
    context_ids={eid for c in context_pool for eid in c["event_ids"]}
    path_ids={eid for p in g["path_alternatives"] for eid in p["event_ids"]}
    relevant=[]
    for tid,t in task_index.items():
        if tid in task_ids:
            relevant.append({"task_id":tid,"relevance":"direct"})
        elif set(t.get("event_ids",[])) & (used|context_ids|path_ids):
            relevant.append({"task_id":tid,"relevance":"shared_event_evidence"})
        else:
            # Preserve interval-only tasks as contextual opportunities if
            # their search/media overlaps an explicit inter-anchor region.
            intervals=[x["certain_interior"] for x in g["source_candidate"].get("interval_context",[])
                       if x.get("certain_interior")]
            search=[t["search_interval"]] if t.get("search_interval") else t.get("media_windows",[])
            if not t.get("candidate_id") and any(a<d and b>c for a,b in intervals for c,d in search):
                relevant.append({"task_id":tid,"relevance":"inter_anchor_search_context"})
    g["observation_task_refs"]=relevant
    missing=[n["node_id"] for n in nodes if n["required"] and not n["material_ids"]]
    diagnostics=list(g["diagnostics"])
    for m in materials:
        if len(m["story_node_ids"])>1:
            diagnostics.append({"kind":"shared_physical_material","material_id":m["material_id"],
                                "story_node_ids":m["story_node_ids"]})
    for a,b in zip(materials,materials[1:]):
        diagnostics.append({"kind":"unselected_source_gap","from":a["material_id"],"to":b["material_id"],
                            "interval":[a["media_window"][1],b["media_window"][0]]})
    g["diagnostics"]=diagnostics
    return {"story_graph":g,"materials":materials,"initial_edl":edl,
            "context_pool":context_pool,"observation_tasks":[deepcopy(task_index[x["task_id"]]) for x in relevant],
            "story_diagnostics":{"missing_required_nodes":missing,"diagnostics":diagnostics,
                "n_segments":len(edl),"duration_sec":sum(x["media_out"]-x["media_in"] for x in edl),
                "structurally_complete":not missing,"n_context_candidates":len(context_pool),
                "quality_verified":False,"first_live_verified":False,"release_authorized":False},
            "preview_only":True,"release_authorized":False}
