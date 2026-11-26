"""R4/R5 integrated research agent over frozen R3 stories.

A generic critic/planner uses Story Graph, all eligible interval atoms and
actual videos. One local revision at a time; feedback from real comparative
verification drives the next round. No autonomous delivery authorization.
"""
import argparse
import json
from copy import deepcopy
from pathlib import Path
from template_graph import read,write,check
from general_agent_protocol import (seed_rows,task_windows,inventory,story_intervals,
    parse_hypotheses,validate_observation,trial_revision,verifier_decision,replay_windows,
    cut_identity,overlaps)

def compact(obj):
    return json.dumps(obj,ensure_ascii=False,separators=(",",":"))

def prepare(story_dir,evidence,events,*,max_clip_sec=40):
    d=Path(story_dir)
    graph=read(d/"story_graph.json")
    check(graph["video_id"]==evidence["video_id"] and graph["input_tier"]==evidence["input_tier"],
          "story source mismatch")
    initial=read(d/"initial_edl.json")
    legacy=read(d/"legacy_seed.json") if graph["agent_seed"]["file"]=="legacy_seed.json" else None
    if legacy is not None:
        from general_agent_video import sha
        check(sha(d/"legacy_seed.json")==graph["legacy_seed"]["sha256"],"legacy seed hash mismatch")
    rows=seed_rows(graph,initial,legacy,evidence)
    tasks=read(d/"observation_tasks.json")
    check(len({t["task_id"] for t in tasks})==len(tasks) and
          all(t["video_id"]==evidence["video_id"] for t in tasks),"observation task source mismatch")
    candidates=[]
    for t in tasks:
        for i,w in enumerate(task_windows(t,evidence,max_clip_sec),1):
            candidates.append({"target_id":t["task_id"]+":tile:"+str(i),"task_id":t["task_id"],
                "type":t["task_type"],"source_window":list(w),"event_ids":t.get("event_ids",[]),
                "questions":t.get("questions",[]),"task":t})
    for r in rows:
        candidates.append({"target_id":"seed:"+r["segment_id"],"type":"existing_segment_review",
            "source_window":[r["media_in"],r["media_out"]],"event_ids":r.get("event_ids",[]),
            "segment_id":r["segment_id"],"questions":["verify content, boundaries and broadcast phase"]})
    return {"schema":"sportscausal_general_agent_input_v1","video_id":graph["video_id"],
        "graph":graph,"seed_edl":rows,"tasks":tasks,"targets":candidates,
        "intervals":story_intervals(graph,evidence),
        "context_pool":read(d/"context_pool.json"),"nonlive_windows":replay_windows(events,evidence["duration_sec"]),
        "http_calls":0,"quality_verified":False,"first_live_verified":False}

def story_view(prepared,rows):
    g=prepared["graph"]
    return {"template":g["template_id"],"category":g["category"],"subtype":g["subtype"],
        "narrative_goal":g["narrative_goal"],"subjects":g["subjects"],
        "nodes":[{k:n[k] for k in ("node_id","node_type","actor","actor_role","score","score_beneficiary",
                  "predicate","event_ids","media_windows","required","perspectives","observation_task_ids") if k in n}
                 for n in g["nodes"]],
        "edges":g["edges"],"current_edl":rows,
        "diagnostics":g["diagnostics"]}

def run_agent(prepared,evidence,backend,out,*,max_rounds=2):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    rows=deepcopy(prepared["seed_edl"])
    initial=deepcopy(rows); history=[]; observations={}; tried=set()
    graph=deepcopy(prepared["graph"])
    # Keep the actual historical candidate seed separate; all working rows
    # are unverified previews. Critic views video, not just the graph.
    baseline=backend.render_preview(rows,out/"seed_preview.mp4","baseline_seed")
    current_preview=baseline
    stop="round_limit"
    for ri in range(1,max_rounds+1):
        d=out/("round_%02d"%ri); d.mkdir(exist_ok=False)
        record={"round":ri,"accepted":False}
        if backend.calls_left()<1:
            stop="budget_exhausted"; break
        try:
            critic=backend.query("critic",
                "Watch the supplied complete silent preview, using graph only as context. "
                "Identify a concrete missing, misleading, redundant or poorly bounded story element. "
                "Check the specified template, not a generic comeback. Distinguish actual observations "
                "from hypotheses. A large source gap alone is not a defect. If no worthwhile change "
                "is apparent, say keep. Return JSON {action: 'investigate' or 'keep', issue: string, "
                "interval_id: existing ID or null, evidence: string}. No new times. "
                +compact({"story":story_view({**prepared,"graph":graph},rows),
                    "intervals":prepared["intervals"],"tasks":prepared["tasks"],"history":history}),
                d,[current_preview])
            record["critic"]=critic
            check(critic.get("action") in {"investigate","keep"} and isinstance(critic.get("issue"),str)
                  and critic["issue"].strip(),"invalid critic output")
            if critic["action"]=="keep":
                stop="critic_no_worthwhile_change"; history.append(record); break
            interval=next((x for x in prepared["intervals"] if x["interval_id"]==critic.get("interval_id")),None)
            hypotheses=[]; targets=deepcopy(prepared["targets"])
            # Story-First is conditional on a narrative interval, not a
            # prerequisite for task-based goal recovery or verification.
            if interval is not None and backend.calls_left()>=4:
                events=inventory(evidence,*interval["window"])
                if events:
                    raw=backend.query("story_first",
                        "Generate 0..5 distinct event-grounded story hypotheses that could improve "
                        "this specific narrative interval. Consider local patterns and multi-event "
                        "combinations; don't work backward from a goal or force causality. "
                        "Use only supplied event IDs in chronological order. No score/ranking. "
                        "Return JSON {hypotheses:[{event_ids:[...],hypothesis:string,narrative_function:string}]}. "
                        +compact({"story":story_view({**prepared,"graph":graph},rows),
                            "issue":critic["issue"],"interval":interval,"all_interval_events":events,
                            "previous_feedback":history}),d)
                    hypotheses=parse_hypotheses(raw,interval,events)
                    for h in hypotheses:
                        # Preserve disjoint evidence; use a bounded
                        # continuous span per nearby group of events.
                        windows=h["media_windows"]
                        groups=[]
                        for lo,hi in sorted(windows):
                            if groups and hi-groups[-1][0]<=backend.max_clip_sec:
                                groups[-1][1]=max(groups[-1][1],hi)
                            else:
                                groups.append([lo,hi])
                        for i,w in enumerate(groups,1):
                            if w[1]-w[0]<=backend.max_clip_sec:
                                targets.append({"target_id":h["hypothesis_id"]+":part:"+str(i),
                                    "type":"story_first_hypothesis","source_window":w,
                                    "event_ids":h["event_ids"],"hypothesis":h,
                                    "questions":["verify actual sequence and narrative relation"]})
            record["hypotheses"]=hypotheses
            targets=[t for t in targets if tuple(t["source_window"]) not in tried]
            if not targets or backend.calls_left()<3:
                stop="no_new_target_or_budget"; history.append(record); break
            # No Causal-4 scalar is passed to Planner. It decides whether
            # an observation is useful and selects a concrete source target.
            plan=backend.query("plan_observation",
                "Choose ONE available observation target addressing the critic issue. "
                "For a missing score action prioritize actual goal localization, not scoreboard. "
                "For a relation path inspect continuous actions, not just endpoints. "
                "Do not force an edit; choose keep if no target is relevant. "
                "Return JSON {action:'observe' or 'keep',target_id:string or null,rationale:string}. "
                +compact({"story":story_view({**prepared,"graph":graph},rows),
                    "critic":critic,"targets":targets,"feedback":history}),d)
            record["plan_observation"]=plan
            if plan.get("action")=="keep":
                stop="planner_no_relevant_target"; history.append(record); break
            check(plan.get("action")=="observe","invalid observation plan")
            target=next((t for t in targets if t["target_id"]==plan.get("target_id")),None)
            check(target is not None,"unbound observation target")
            w=target["source_window"]
            check(w[1]-w[0]<=backend.max_clip_sec,"observation exceeds bounded native window")
            tried.add(tuple(w))
            clip=backend.observe_clip(w,d/"source.mp4","source:"+str(ri))
            write(d/"source_manifest.json",clip)
            raw=backend.query("observe",
                "Inspect this continuous original broadcast clip (silent, transcoded 5fps). "
                "Answer the target questions using pixels only; annotation is a locator. "
                "Use SOURCE seconds in the given interval, never edited story time. "
                "If a target goal is not actually visible, return CONTRADICTED or UNCERTAIN. "
                "Distinguish live/replay/slow motion and uncertainty. Do not claim first occurrence "
                "from a local clip alone. Return JSON {clip_id:string,finding:'SUPPORTED'|'CONTRADICTED'|'UNCERTAIN',"
                "description:string,broadcast:'LIVE'|'REPLAY'|'UNCERTAIN',action_window_sec:[start,end] or null,"
                "event_ids:[known IDs],goal_beneficiary:'team_1'|'team_2'|null,goal_visible:boolean}. "
                +compact({"clip_id":clip["clip_id"],"source_window":w,"target":target,
                    "teams":evidence.get("teams"),"source_events":inventory(evidence,*w)}),d,[clip])
            obs=validate_observation(raw,clip,backend.source_sha,evidence["duration_sec"])
            obs_id="obs:"+str(ri); obs["observation_id"]=obs_id; obs["target_id"]=target["target_id"]
            # Bind recovered missing nodes only to their own task and a
            # visually observed goal consistent with the expected beneficiary.
            obs["story_node_ids"]=[]
            task=target.get("task") or {}
            for n in graph["nodes"]:
                if (n["node_type"]=="missing" and task.get("task_id") in n.get("observation_task_ids",[])
                    and obs["finding"]=="SUPPORTED" and obs.get("goal_visible") is True
                    and obs.get("goal_beneficiary")==task.get("score_beneficiary")):
                    obs["story_node_ids"].append(n["node_id"])
            observations[obs_id]=obs; record["observation"]=obs
            write(d/"observation.json",obs)
            if backend.calls_left()<2:
                stop="budget_before_revision"; history.append(record); break
            revision=backend.query("plan_revision",
                "Use the observed video evidence to choose a single local trial edit. "
                "Keep if observation adds no narrative value. No fabricated timestamps: "
                "add/replace/trim use exactly the observed action_window; drop only with "
                "contrary visual evidence. Preserve required anchors unless directly overturned. "
                "Return JSON {action:'add'|'replace'|'trim'|'drop'|'keep',target_segment_id:string or null,"
                "observation_id:string,rationale:string,anchor_overturn:boolean}. "
                +compact({"story":story_view({**prepared,"graph":graph},rows),
                    "critic":critic,"observation":obs,"target":target,"feedback":history}),d)
            record["revision"]=revision
            check(revision.get("observation_id")==obs_id or revision.get("action")=="keep",
                  "revision must use current observation")
            if revision.get("action")=="keep":
                record["feedback"]="planner_keep_after_observation"; history.append(record); continue
            trial=trial_revision(rows,revision,observations,evidence,prepared["nonlive_windows"])
            if cut_identity(trial)==cut_identity(rows):
                record["feedback"]="identical_cut"; history.append(record); continue
            write(d/"trial_edl.json",trial)
            candidate=backend.render_preview(trial,d/"trial_preview.mp4","candidate:"+str(ri))
            comparison=backend.query("verify",
                "Compare the TWO complete edited silent videos, baseline then candidate. "
                "Judge the specified story, not duration or aesthetics alone. Determine whether "
                "the original defect was resolved, whether the new action is relevant and coherent, "
                "and whether a new defect/replay/incorrect action was introduced. "
                "Cite visible details from both cuts and be willing to reject. "
                "Return JSON {decision:'ACCEPT'|'REJECT'|'UNCERTAIN',rationale:string,"
                "original_issue_resolved:boolean,new_defect:boolean,before_evidence:string,after_evidence:string}. "
                +compact({"story":story_view({**prepared,"graph":graph},rows),
                    "critic":critic,"revision":revision,"source_observation":obs,
                    "baseline_edl":rows,"candidate_edl":trial}),d,[current_preview,candidate])
            verdict=verifier_decision(comparison,True,backend.real_visual)
            record.update(verifier=comparison,decision=verdict)
            if verdict=="ACCEPT":
                rows=trial; current_preview=candidate; record["accepted"]=True
                # A localized missing action is a video-supported candidate,
                # not a gold annotation or independently proven first live.
                for n in graph["nodes"]:
                    if n["node_id"] in obs["story_node_ids"]:
                        n["node_type"]="anchor"
                        n["localization_status"]="video_supported_candidate"
                        n["media_windows"]=[obs["action_window_sec"]]
                        n["source_observation_id"]=obs_id
                graph.setdefault("accepted_revisions",[]).append({"round":ri,"observation_id":obs_id,
                    "revision":revision,"verifier":comparison})
            record["feedback"]=comparison.get("rationale")
            history.append(record)
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            record["feedback"]="execution_or_evidence_error:"+type(exc).__name__+":"+str(exc)
            history.append(record)
            stop="execution_or_evidence_error"
            break
        finally:
            write(d/"round.json",record)
    write(out/"initial_seed_edl.json",initial)
    write(out/"refined_edl.json",rows)
    write(out/"refined_story_graph.json",graph)
    write(out/"observations.json",observations)
    report={"schema":"sportscausal_general_agent_run_v1","story_id":graph["story_id"],
            "video_id":graph["video_id"],"rounds":history,"stop_reason":stop,
            "n_accepted":sum(r["accepted"] for r in history),
            "changed":cut_identity(rows)!=cut_identity(initial),"usage":backend.usage(),
            "current_preview":current_preview,"observation_mode":"native_video_preview",
            "quality_verified":False,"first_live_verified":False,"release_authorized":False,
            "fixture_only":not backend.real_visual}
    write(out/"report.json",report)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("story-dir","evidence","events","out-dir"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--source")
    p.add_argument("--source-manifest")
    p.add_argument("--legacy-algo-dir",help="existing 11.20sstory_chain/algo on server")
    p.add_argument("--enable-real-api",action="store_true")
    p.add_argument("--approve-budget",action="store_true")
    p.add_argument("--max-calls",type=int,default=8)
    p.add_argument("--max-cost-usd",type=float,default=0.05)
    p.add_argument("--max-rounds",type=int,default=2)
    p.add_argument("--allow-dev",action="store_true")
    a=p.parse_args(); e=read(a.evidence); raw=read(a.events)
    events=raw if isinstance(raw,list) else raw["events"]
    check(a.allow_dev or e["input_tier"] in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires --allow-dev")
    # The replay/slow-motion intervals come from the same original event
    # document, including rows excluded by Stage 1.2.
    from template_graph import event_window
    by={x["event_id"]:x for x in events}
    for eid,atom in e["atoms"].items():
        check(eid in by,"source events do not contain evidence atom "+eid)
        w=event_window(by[eid],e["duration_sec"])
        check(w is not None and w[0]==atom["window"] and w[1]==atom["t"],"source atom time mismatch "+eid)
    out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=False)
    prepared=prepare(a.story_dir,e,events)
    write(out/"prepared_agent_input.json",prepared)
    if not a.enable_real_api:
        write(out/"report.json",{"status":"PREPARED_ONLY_ZERO_HTTP","http_calls":0,
             "n_targets":len(prepared["targets"]),"n_intervals":len(prepared["intervals"]),
             "quality_verified":False,"first_live_verified":False,"release_authorized":False})
        return
    check(a.approve_budget and a.source and a.source_manifest and a.legacy_algo_dir
          and 0<a.max_calls<=30 and 0<a.max_cost_usd<=1 and 1<=a.max_rounds<=5,
          "explicit real API, source and bounded budget approval required")
    import sys
    sys.path.insert(0,str(Path(a.legacy_algo_dir).resolve()))
    from general_agent_video import NativeBackend
    backend=NativeBackend(a.source,read(a.source_manifest),e,max_calls=a.max_calls,max_cost_usd=a.max_cost_usd)
    run_agent(prepared,e,backend,out,max_rounds=a.max_rounds)

if __name__=="__main__":
    main()
