"""R4/R5.1 — adapt frozen R3 outputs to the ORIGINAL V3-A agent.

This module contains no alternate Planner, Verifier, P1/P2/P3 or loop.
The default command only prepares the native input and calls original P1
preparation with api=None. Rendering/agent execution is a separate opt-in.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from template_graph import check, read, write, number, event_window, known_nonlive

SCHEMA = "sportscausal_r3_legacy_adapter_v1"

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def overlap(a,b):
    return a[0]<b[1] and b[0]<a[1]

def validate_source_events(evidence,doc):
    events=doc if isinstance(doc,list) else doc.get("events")
    check(isinstance(events,list),"native event list required")
    index={}
    for e in events:
        eid=e.get("event_id")
        check(isinstance(eid,str) and eid and eid not in index,"duplicate/missing native event id")
        index[eid]=e
    for eid,a in evidence["atoms"].items():
        check(eid in index,"evidence atom absent from native events: "+eid)
        w=event_window(index[eid],evidence["duration_sec"])
        check(w is not None and w[0]==a["window"] and w[1]==a["t"],"native source PTS mismatch: "+eid)
        check(not known_nonlive(index[eid]),"evidence atom is annotated nonlive: "+eid)
    return events

def _role(n, template_id=None):
    if n.get("kind") in ("score_state","score_outcome"):
        # State sign describes the scoreboard AFTER a goal, not the goal's
        # narrative function. A continuous lead can contain several distinct
        # score changes. Derive each positive-state goal role from its
        # already bound transition, never from a new clip or a case name.
        # Keep other templates and historical legacy seed roles unchanged.
        if (template_id=="lead_preservation" and n.get("kind")=="score_state"
                and n.get("state_sign")==1 and n.get("node_type")=="anchor"):
            roles=n.get("goal_roles") or []
            check(len(roles)==1,"lead anchor requires one bound goal transition")
            b=roles[0].get("score_binding") or {}
            i=b.get("path_index")
            check(type(i) is int and i>0 and i==n.get("score_path_index"),
                  "lead anchor score transition identity mismatch")
            check(b.get("score_after")==n.get("score") and b.get("event_id") in n.get("event_ids",[]),
                  "lead anchor score/event binding mismatch")
            actor=n.get("actor")
            beneficiary=b.get("score_beneficiary")
            check(actor in {"team_1","team_2"} and beneficiary in {"team_1","team_2"},
                  "lead anchor requires bound teams")
            def scores(value):
                parts=str(value).split(":")
                check(len(parts)==2 and all(p.isdigit() for p in parts),"invalid bound score")
                return tuple(int(p) for p in parts)
            before,after=scores(b.get("score_before")),scores(b.get("score_after"))
            delta=tuple(a-z for a,z in zip(after,before))
            check(delta in {(1,0),(0,1)},"not a single-goal score transition")
            scoring_side=delta.index(1)
            subject_side=scoring_side if actor==beneficiary else 1-scoring_side
            pre=before[subject_side]-before[1-subject_side]
            post=after[subject_side]-after[1-subject_side]
            check(post>0,"lead anchor contradicts bound score transition")
            if pre==0 and actor==beneficiary:
                return "go_ahead_goal_action"
            check(pre>0,"lead anchor has incompatible previous score")
            if actor==beneficiary:
                return f"lead_extend_{i}_goal_action"
            return f"opponent_reduce_lead_{i}_goal_action"
        return {-1:"opponent_opening_goal_action",0:"equalizer_goal_action",
                1:"go_ahead_goal_action"}.get(n.get("state_sign"),"scoring_goal_action")
    return n.get("predicate") or "required_path_context"

def _node_summary(n):
    return {k:deepcopy(n[k]) for k in ("node_id","node_type","kind","predicate","actor","actor_role",
        "required","score","state_sign","score_beneficiary","event_ids","media_windows",
        "action_time_interval","observation_task_ids","localization_status") if k in n}

def _span(r,duration):
    a,b=r.get("media_in"),r.get("media_out")
    check(number(a) and number(b) and 0<=a<b<=duration,"invalid seed media span")
    return [a,b]

def compact_story_context(graph,rows,tasks,evidence):
    """First alphabetic plan field survives the original P1 9000-char cap.

    Keep explicit template/goal/subjects even when the full plan is long.
    Goal transitions are from R3 score bindings, never inferred from team
    identity or a generic goal label.
    """
    goals=[]
    for n in graph["nodes"]:
        if not n["required"]:
            continue
        for role in n.get("goal_roles",[]):
            b=role.get("score_binding") or {}
            if b.get("score_before") and b.get("score_after"):
                goals.append({"node_id":n["node_id"],"score_before":b["score_before"],
                    "score_after":b["score_after"],"confirmation_t_sec":b.get("confirmation_t_sec"),
                    "action_t_sec":b.get("action_t_sec"),"event_id":b.get("event_id")})
        for t in tasks:
            if n["node_type"]=="missing" and t["task_id"] in n.get("observation_task_ids",[]) and t.get("task_type")=="missing_goal_localization":
                goals.append({"node_id":n["node_id"],"score_before":t["score_before"],
                    "score_after":t["score_after"],"confirmation_t_sec":t["confirmation_t_sec"],
                    "search_interval":t["search_interval"],"task_id":t["task_id"]})
    # Full graph/EDL remains separately available. Only include compact
    # chain IDs/known membership, not unsupported causal claims.
    required=[{"node_id":n["node_id"],"type":n["node_type"],
               "role":_role(n,graph["template_id"]) if n["node_type"] in {"anchor","missing"} else n["node_type"],
               "actor":n.get("actor"),"score":n.get("score"),
               "segment_ids":[r["segment_id"] for r in rows if n["node_id"] in r["required_story_node_ids"]]}
              for n in graph["nodes"] if n["required"]]
    context={"schema":"r3_agent_story_context_v1","template_id":graph["template_id"],
             "category":graph["category"],"subtype":graph["subtype"],
             "narrative_goal":deepcopy(graph["narrative_goal"]),"subjects":deepcopy(graph["subjects"]),
             "teams":deepcopy(evidence.get("teams",{})),
             "goal_targets":goals,"required_nodes":required,
             "chain_ids":list(dict.fromkeys(c for r in rows for c in r.get("short_chain_ids",[]))),
             "observation_task_ids":[t["task_id"] for t in tasks],
             "causal_relations_are_hypotheses":True}
    # Preserve the full structured context for Critic; put the essential
    # template fields in a separately bounded alphabetically early field.
    return context

def adapt(graph,initial,legacy,tasks,context,evidence,events,*,seed="auto"):
    check(graph["schema"]=="sportscausal_story_graph_v1" and
          graph["video_id"]==evidence["video_id"] and graph["input_tier"]==evidence["input_tier"],
          "R3 source mismatch")
    check(graph.get("first_live_verified") is False and graph.get("release_authorized") is False,
          "unexpected R3 release state")
    check(seed in {"auto","r3","legacy"},"unknown seed option")
    use_legacy=seed=="legacy" or (seed=="auto" and graph["agent_seed"]["file"]=="legacy_seed.json")
    if use_legacy:
        check(graph["template_id"]=="comeback" and isinstance(legacy,dict),"native comeback seed required")
        # Preserve historical role semantics and exact source windows.
        # Native scoreboard-confirmation rows and title placeholders are
        # not live action footage; the immutable plan remains separate.
        source=[r for r in legacy["edl"] if r.get("shot_kind")=="live"]
        basis="legacy_action_candidates"
    else:
        source=initial
        basis="r3_anchor_materials"
    nodes={n["node_id"]:n for n in graph["nodes"]}
    check(len(nodes)==len(graph["nodes"]),"duplicate story nodes")
    rows=[]; previous=0; seen=set()
    for i,r in enumerate(source,1):
        w=_span(r,evidence["duration_sec"])
        sid=r["segment_id"]
        check(sid not in seen and previous<=w[0],"duplicate or nonchronological seed")
        seen.add(sid); previous=w[1]
        if use_legacy:
            bound=[n["node_id"] for n in nodes.values() if n["required"] and
                   any(overlap(w,x) for x in n.get("media_windows",[]))]
            # Historical event IDs may be synthetic adapters. Keep them as
            # provenance, separately attach native source atoms by PTS.
            event_ids=[a["event_id"] for a in sorted(evidence["atoms"].values(),key=lambda a:a["t"])
                       if w[0]<=a["t"]<w[1]]
        else:
            bound=list(r["story_node_ids"])
            check(set(bound)<=set(nodes),"unbound R3 segment node")
            event_ids=list(r["event_ids"])
            check(all(eid in evidence["atoms"] and overlap(w,evidence["atoms"][eid]["window"])
                      for eid in event_ids),"unbound R3 event")
        # The same physical segment may represent several semantic nodes.
        required=[nid for nid in bound if nodes[nid]["required"]]
        anchors=[nid for nid in required if nodes[nid]["node_type"]=="anchor"]
        role=r.get("role") if use_legacy else (_role(nodes[anchors[0]],graph["template_id"]) if anchors else "story_context")
        check(isinstance(role,str) and role,"missing native role")
        row={**deepcopy(r),"segment_id":sid,"video_id":graph["video_id"],"event_ids":event_ids,
             "story_node_ids":bound,"required_story_node_ids":required,
             "story_anchor":False,"role":role,"beat":r.get("beat") or role,
             "shot_kind":"live","is_replay":False,"include_in_cut":True,
             "preview_only":True,"first_live_verified":False,"first_live_status":"NOT_VERIFIED",
             "verification_status":"draft","edl_index":i,"narrative_order":i,
             "source_media_order":w[0],"adapter_seed_basis":basis}
        if use_legacy:
            row["legacy_event_ids"]=deepcopy(r.get("event_ids",[]))
        rows.append(row)
    check(bool(rows),"no playable seed rows")
    # Original P1 pairs EDL semantic anchors, not graph nodes. Select one
    # representative *existing* segment per localized anchor; preserve every
    # material and all graph memberships, never create a virtual video row.
    anchor_bindings=[]
    for n in nodes.values():
        if n["node_type"]!="anchor" or not n["required"]:
            continue
        matches=[r for r in rows if n["node_id"] in r["required_story_node_ids"]]
        check(matches,"required localized anchor not represented in seed: "+n["node_id"])
        t=n.get("anchor_t")
        selected=next((r for r in matches if number(t) and r["media_in"]<=t<=r["media_out"]),matches[0])
        selected["story_anchor"]=True
        anchor_bindings.append({"node_id":n["node_id"],"segment_id":selected["segment_id"],
                                "all_segment_ids":[r["segment_id"] for r in matches]})
    task_index={t["task_id"]:t for t in tasks}
    check(len(task_index)==len(tasks) and all(t["video_id"]==graph["video_id"] for t in tasks),
          "task source mismatch")
    missing=[]
    for n in nodes.values():
        if n["node_type"]=="missing":
            ids=n.get("observation_task_ids",[])
            check(bool(ids) and set(ids)<=set(task_index),"missing node without bound task")
            missing.append({"node":_node_summary(n),"tasks":[deepcopy(task_index[i]) for i in ids]})
    # Preserve original nonlive rows for P2 replay exclusion; legacy broad
    # candidate spans may overlap them. Flag actual overlaps, never silently
    # trim historical windows or turn them into verified footage.
    nonlive=[]
    for e in events:
        if known_nonlive(e):
            w=event_window(e,evidence["duration_sec"])
            if w:
                nonlive.append((e["event_id"],w[0]))
    conflicts=[{"segment_id":r["segment_id"],"replay_event_ids":[eid for eid,w in nonlive
               if overlap([r["media_in"],r["media_out"]],w)]} for r in rows]
    conflicts=[c for c in conflicts if c["replay_event_ids"]]
    teams=evidence.get("teams",{})
    team_names={side:(teams.get(t) or {}).get("name",t) for side,t in (("left","team_1"),("right","team_2"))}
    subject=graph["subjects"][0] if len(graph["subjects"])==1 else None
    side={"team_1":"left","team_2":"right"}.get(subject)
    protagonist={"side":side,"team_name":team_names.get(side),"teams":team_names}
    # The original Story-First extracts this story_plan and template/beats.
    # Keep compact narrative semantics near the beginning; all full R3
    # graph/tasks/short chains remain separately archived for traceability.
    agent_context=compact_story_context(graph,rows,tasks,evidence)
    essential={k:agent_context[k] for k in ("schema","template_id","category","subtype","narrative_goal","subjects","teams")}
    plan={"a_story_template_context":essential,"agent_story_context":agent_context,
          "schema_version":"r3_legacy_agent_input_v1","algorithm":"R3",
          "template_id":graph["template_id"],"template_name":graph["subtype"],
          "template":{"category":graph["category"],"subtype":graph["subtype"],
                      "narrative_goal":graph["narrative_goal"],"subjects":graph["subjects"],
                      "narrative_edges":[{k:edge[k] for k in ("from","to","edge_type","relation","causal_verified") if k in edge}
                                         for edge in graph.get("edges",[]) if edge.get("selected") is not False]},
          "title":graph["subtype"],"match_id":graph["video_id"],"protagonist":protagonist,
          "beats":[{**_node_summary(n),"role":_role(n,graph["template_id"]) if n["node_type"] in {"anchor","missing"} else n["node_type"]}
                   for n in nodes.values() if n["required"] or n["node_type"]=="transition"],
          "story_tier":graph["input_tier"],"missing_evidence":missing,
          "segments":deepcopy(rows),"edl":deepcopy(rows),"candidate_edl":deepcopy(rows),
          "render_ready_edl":[],"render_ready":False,"first_live_verified":False,
          "release_authorized":False,"verification_status":"not_render_ready",
          "r3_adapter":{"schema":SCHEMA,"story_id":graph["story_id"],"seed_basis":basis,
                        "input_tier":graph["input_tier"],"anchor_bindings":anchor_bindings,
                        "missing_node_ids":[m["node"]["node_id"] for m in missing]}}
    check(len(json.dumps({"a_story_template_context":essential},ensure_ascii=False,sort_keys=True))<9000,
          "essential story template exceeds original P1 cap")
    return {"schema":SCHEMA,"plan":plan,"edl":rows,"anchor_bindings":anchor_bindings,
            "missing":missing,"graph":deepcopy(graph),"context_pool":deepcopy(context),
            "observation_tasks":deepcopy(tasks),"predicted_short_chains":deepcopy(evidence["chains"]),
            "seed_basis":basis,"annotated_nonlive_overlaps":conflicts,
            "duration_sec":sum(r["media_out"]-r["media_in"] for r in rows),
            "first_live_verified":False,"release_authorized":False}

def load_adapter(story_dir,evidence_path,events_path,seed="auto"):
    d=Path(story_dir)
    e=read(evidence_path)
    events=validate_source_events(e,read(events_path))
    g=read(d/"story_graph.json")
    legacy_path=d/"legacy_seed.json"
    legacy=read(legacy_path) if legacy_path.is_file() else None
    if legacy is not None:
        check(sha(legacy_path)==g["legacy_seed"]["sha256"],"legacy byte hash mismatch")
    bundle=adapt(g,read(d/"initial_edl.json"),legacy,read(d/"observation_tasks.json"),
                 read(d/"context_pool.json"),e,events,seed=seed)
    bundle["input_hashes"]={str(p):sha(p) for p in [Path(evidence_path),Path(events_path),
        d/"story_graph.json",d/"initial_edl.json",d/"observation_tasks.json",d/"context_pool.json"]
        +([legacy_path] if legacy_path.is_file() else [])}
    return bundle,events

def prepare_original_p1(bundle,events,out,algo_dir):
    # Actual original functions; no model or video operations.
    sys.path.insert(0,str(Path(algo_dir).resolve()))
    from story_video_agent_v3.story_first_hypotheses import adjacent_story_anchor_pairs
    from story_video_agent_v3.story_first_search import discover_story_first
    from story_video_agent_v3.fresh_e2e_cli import validate_render_rows
    rows=validate_render_rows(bundle["edl"])
    pairs=adjacent_story_anchor_pairs(rows)
    pool=discover_story_first(edl=rows,story_plan=bundle["plan"],events=events,
         source_sha=None,out_dir=Path(out)/"original_p1",api=None,data_tier=bundle["graph"]["input_tier"])
    return {"pairs":pairs,"intervals":pool["intervals"],"proposals":len(pool["proposals"]),
            "http_calls":0,"p1_function":"story_first_search.discover_story_first",
            "missing_nodes_not_p1_anchors":[m["node"]["node_id"] for m in bundle["missing"]]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("story-dir","evidence","events","algo-dir","out-dir"):
        p.add_argument("--"+name,required=True)
    p.add_argument("--seed",choices=["auto","r3","legacy"],default="auto")
    p.add_argument("--allow-dev",action="store_true")
    a=p.parse_args()
    bundle,events=load_adapter(a.story_dir,a.evidence,a.events,a.seed)
    check(a.allow_dev or bundle["graph"]["input_tier"] in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires explicit opt-in")
    out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=False)
    write(out/"story_plan.json",bundle["plan"])
    write(out/"candidate_edl.json",bundle["edl"])
    write(out/"adapter_bundle.json",bundle)
    preflight=prepare_original_p1(bundle,events,out,a.algo_dir)
    write(out/"report.json",{"schema":SCHEMA,"status":"ADAPTER_PREPARED_ZERO_HTTP",
        "video_id":bundle["graph"]["video_id"],"story_id":bundle["graph"]["story_id"],
        "seed_basis":bundle["seed_basis"],"n_segments":len(bundle["edl"]),
        "duration_sec":bundle["duration_sec"],"n_anchor_bindings":len(bundle["anchor_bindings"]),
        "n_observation_tasks":len(bundle["observation_tasks"]),
        "annotated_nonlive_overlaps":bundle["annotated_nonlive_overlaps"],
        "input_hashes":bundle["input_hashes"],"original_p1":preflight,
        "first_live_verified":False,"release_authorized":False})

if __name__=="__main__":
    main()
