"""Combined R2b/R2c preflight over saved R2a.4 artifacts, no historical rerun."""
from pathlib import Path
import argparse
from copy import deepcopy
from template_graph import read,write,check
from state_story_patterns import state_candidates
from relation_story_patterns import relation_candidates
from phase_story_patterns import phase_candidates

def template(tid,category,subtype,goal,pattern):
    return {"template_id":tid,"category":category,"subtype":subtype,
            "narrative_goal":[goal],"pattern":pattern}

def default_templates():
    state=lambda signs,terminal,selection:{"operator":"state_transition","signs":signs,
                                           "terminal_sign":terminal,"selection":selection}
    path=lambda start:{"operator":"relation_path","start_predicate":start,
                       "end_predicate":"scoring_outcome","max_span_sec":45,"max_edge_gap_sec":15}
    return [
        read(Path(__file__).parent/"patterns"/"comeback.json"),
        template("equalization","战局故事链","落后追平","落后到追平的阶段性战局变化",state([-1,0],None,"all")),
        template("lead_preservation","战局故事链","领先守成","最后一段领先状态及后续守成素材候选",state([0,1],1,"last")),
        template("set_piece_breakthrough","关键转折故事链","定位球战术执行与破局",
                 "定位球到比分结果的有序关系路径候选",path("set_piece_execution")),
        template("turnover_to_goal","关键转折故事链","攻守转换与关键破门",
                 "球权夺回到比分结果的关系路径候选",path("turnover_recovery")),
        template("threat_phase_change","攻防故事链","攻势换手",
                 "连续观测到的攻防威胁序列发生主体切换",
                 {"operator":"phase_change","predicate":"attacking_threat","min_episodes_per_phase":2})
    ]

def validate_sources(evidence,graph,bundle,score):
    check(graph["schema"]=="v3r_general_role_graph_v1"
          and bundle["schema"]=="v3r_general_role_episodes_v1","R2a.4 artifacts required")
    check(all(x["video_id"]==evidence["video_id"] for x in (graph,bundle,score))
          and all(x["input_tier"]==evidence["input_tier"] for x in (graph,bundle)),"source mismatch")
    check(graph["goal_bindings"]==bundle["goal_bindings"]
          and graph["observation_tasks"]==bundle["observation_tasks"]
          and graph["edges"]==bundle["local_links"],"graph/bundle mismatch")
    by={a["event_id"]:a for a in graph["atoms"]}
    check(len(by)==len(graph["atoms"]) and set(by)==set(evidence["atoms"]),"atom coverage mismatch")
    for eid,a in by.items():
        b=evidence["atoms"][eid]
        check(all(a.get(k)==b.get(k) for k in ("t","window","type","broadcast_phase","attributes"))
              and (a.get("notes") or "")==(b.get("notes") or ""),"atom mismatch "+eid)
    for ep in bundle["episodes"]:
        check(all(e in by and by[e]["broadcast_phase"]=="LIVE" for e in ep["event_ids"]),
              "unbound/nonlive episode")
    return by

def run(evidence,graph,bundle,score,templates):
    validate_sources(evidence,graph,bundle,score)
    results={}
    for t in templates:
        tid=t["template_id"]
        check(tid not in results,"duplicate template ID")
        op=t["pattern"]["operator"]
        extra={}
        if op=="state_transition":
            candidates=state_candidates(t,score,bundle)
        elif op=="relation_path":
            candidates=relation_candidates(t,graph,evidence)
        elif op=="phase_change":
            extra=phase_candidates(t,bundle)
            candidates=extra.pop("candidates")
        else:
            raise ValueError("unsupported R2b/c operator "+op)
        results[tid]={"schema":"sportscausal_story_anchors_v2","video_id":evidence["video_id"],
            "input_tier":evidence["input_tier"],"template":deepcopy(t),"operator":op,
            "candidates":candidates,**extra,"quality_verified":False,"first_live_verified":False,
            "release_authorized":False}
    return {"schema":"sportscausal_r2bc_preflight_v1","video_id":evidence["video_id"],
            "input_tier":evidence["input_tier"],"http_calls":0,
            "frozen_r2a4_reused":True,"results":results,
            "observation_tasks":deepcopy(graph["observation_tasks"]),
            "quality_verified":False,"first_live_verified":False,"release_authorized":False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",required=True)
    p.add_argument("--r2a4-dir",required=True)
    p.add_argument("--score-path",required=True)
    p.add_argument("--template",action="append",help="explicit external template JSON; repeat for multiple")
    p.add_argument("--template-id",action="append",help="select named built-in templates")
    p.add_argument("--out-dir",required=True)
    p.add_argument("--allow-dev",action="store_true")
    a=p.parse_args()
    e=read(a.evidence)
    check(a.allow_dev or e.get("input_tier") in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development input requires --allow-dev")
    d=Path(a.r2a4_dir)
    templates=[read(t) for t in a.template] if a.template else default_templates()
    if a.template_id:
        selected=set(a.template_id)
        check(selected<={t["template_id"] for t in templates},"unknown selected template")
        templates=[t for t in templates if t["template_id"] in selected]
    pack=run(e,read(d/"relation_graph.json"),read(d/"causal_episodes.json"),
             read(a.score_path),templates)
    out=Path(a.out_dir)
    out.mkdir(parents=True,exist_ok=False)
    for tid,r in pack["results"].items():
        # Explicit external template IDs are used as filenames.
        check(tid and all(c.isascii() and (c.isalnum() or c in "_-") for c in tid),"invalid template filename")
        write(out/(tid+".json"),r)
    write(out/"anchor_pack.json",pack)
    write(out/"summary.json",{"video_id":pack["video_id"],"input_tier":pack["input_tier"],
        "http_calls":0,"frozen_r2a4_reused":True,"n_observation_tasks":len(pack["observation_tasks"]),
        "templates":{tid:{"operator":r["operator"],"n_candidates":len(r["candidates"]),
            "candidates":[{"candidate_id":c["candidate_id"],"subjects":c["subjects"],
                          "nodes":[{"event_ids":n["event_ids"],"actor":n["actor"],
                                    "actor_role":n.get("actor_role"),"kind":n.get("kind")}
                                   for n in c["nodes"]],
                          "unlocalized_state_indices":c.get("unlocalized_state_indices"),
                          "path_alternatives":c.get("path_alternatives"),
                          "switch_search_interval":c.get("switch_search_interval")}
                         for c in r["candidates"]]} for tid,r in pack["results"].items()},
        "quality_verified":False,"first_live_verified":False})

if __name__=="__main__":
    main()
