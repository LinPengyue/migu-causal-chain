"""Stage 2: template-conditioned initial story planner, research-only.

Uses existing delivery API provider only with explicit paid authorization.
Offline preparation and offline response validation never initialize a provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from template_graph import check, read, write, identifier, number
from evidence_representation import compact_request, bind_story

SYSTEM = """You are a sports narrative editor. Generate ONE initial story for the supplied
template, or report no sufficiently supported candidate. The template is a narrative
goal, not a requirement to invent or mechanically fill slots. Inspect the entire
chronological event table and predicted-chain context. Read original notes and
role-specific attributes; distinguish the actor from the opponent and use the team
header. Do not infer same goalkeeper/team from proximity alone. Use multiple
related events per meaningful story instance where evidence supports them.
Seek context, development, meaningful contrast or consequences, not a highlight list.
FULL and PARTIAL chains are predictions, not verified causes. PARTIAL does not
establish missing actions. Only select available atomic event IDs for the media.
Do not invent times, IDs, names, scores, motives, tactics or first-live evidence.
Select necessary footage, in chronological order, with nonoverlapping windows
across instances; overlapping windows within one instance are merged by code.
Do not repeat events. Use the exact supplied slot IDs and cardinalities.
Write concise Chinese narrative hypotheses grounded in selected events.
Every instance must state what it contributes to the overall story and how it
relates to the previous selected instance; the first instance has an empty link.
Associations and editorial transitions need not be causal. No invented causal proof.
Return exactly one JSON object with fields:
title: string, protagonist: string (empty if not supported), summary: string,
no_story_reason: string (empty for a candidate),
bindings: [{slot_id, instances:[{event_ids:[...],chain_ids:[...],
narrative:string,link_from_previous:string}]}].
For no supported candidate use bindings:[], title:"", protagonist:"", summary:"",
and a nonempty no_story_reason. Do not disguise a partial story as complete.
Do not output markdown, extra fields, or video verification claims."""
def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

def messages_for(template, evidence):
    request = compact_request(template, evidence)
    # Replace the old stage 1.2 output instruction to avoid conflicting schemas.
    request.pop("instruction", None)
    return [{"role":"system","content":SYSTEM},
            {"role":"user","content":canonical(request)}]

def parse_response(content):
    check(isinstance(content,str) and content.strip(), "empty planner response")
    s=content.strip()
    if s.startswith("```json\n") and s.endswith("\n```"):
        s=s[8:-4]
    return json.loads(s)

def validate_and_bind(template,evidence,proposal):
    fields={"title","protagonist","summary","no_story_reason","bindings"}
    check(isinstance(proposal,dict) and set(proposal)==fields, "invalid planner response fields")
    for k in fields-{"bindings"}:
        check(isinstance(proposal[k],str), "invalid "+k)
    check(isinstance(proposal["bindings"],list), "invalid bindings")
    if not proposal["bindings"]:
        check(identifier(proposal["no_story_reason"]) and
              not any(proposal[k].strip() for k in ("title","protagonist","summary")),
              "empty candidate must explain absence")
        return {"status":"NO_CANDIDATE","no_story_reason":proposal["no_story_reason"],
                "input_tier":evidence["input_tier"],"preview_only":True,
                "release_authorized":False,"quality_verified":False}
    check(not proposal["no_story_reason"].strip() and identifier(proposal["title"])
          and identifier(proposal["summary"]), "candidate must have title and summary")
    bindings, meta = [], {}
    for row in proposal["bindings"]:
        check(isinstance(row,dict) and set(row)=={"slot_id","instances"}
              and isinstance(row["instances"],list), "invalid planner binding")
        sid=row["slot_id"]
        check(identifier(sid) and sid not in meta,"invalid or repeated slot")
        meta[sid]=[]
        instances=[]
        for ins in row["instances"]:
            check(isinstance(ins,dict) and set(ins)=={"event_ids","chain_ids","narrative","link_from_previous"},
                  "invalid planner instance")
            check(identifier(ins["narrative"]) and isinstance(ins["link_from_previous"],str),
                  "invalid narrative metadata")
            instances.append({k:ins[k] for k in ("event_ids","chain_ids")})
            meta[sid].append(ins)
        bindings.append({"slot_id":sid,"instances":instances})
    bundle=bind_story(template,evidence,{"bindings":bindings})
    check(bool(bundle["candidate_edl"]), "candidate without source media")
    bundle.update(status="CANDIDATE" if bundle["structurally_complete"] else "PARTIAL_CANDIDATE",
                  title=proposal["title"],protagonist_hypothesis=proposal["protagonist"],
                  story_summary_hypothesis=proposal["summary"],
                  narrative_verification_status="UNREVIEWED")
    counters={}
    for i,node in enumerate(bundle["story_graph"]["nodes"]):
        sid=node["slot_id"]
        j=counters.get(sid,0)
        counters[sid]=j+1
        ins=meta[sid][j]
        node["narrative_hypothesis"]=ins["narrative"]
        node["link_from_previous_hypothesis"]=ins["link_from_previous"]
        if i:
            bundle["story_graph"]["edges"][i-1]["narrative_link_hypothesis"]=ins["link_from_previous"]
    return bundle

def run(template,evidence,out,*,api=None,response=None,usage_reader=None,audit_reader=None):
    check(api is None or response is None,"cannot mix real and offline response")
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    messages=messages_for(template,evidence)
    write(out/"planner_messages.json",messages)
    meta={"schema":"sportscausal_planner_run_v1","template_id":template["template_id"],
          "input_tier":evidence["input_tier"],"evidence_sha256":digest(evidence),
          "template_sha256":digest(template),"messages_sha256":digest(messages),
          "prompt_chars":sum(len(m["content"]) for m in messages),
          "prompt_utf8_bytes":sum(len(m["content"].encode("utf-8")) for m in messages),
          "events":len(evidence["atoms"]),"real_model_requested":api is not None,
          "mode":"REAL" if api is not None else "OFFLINE_RESPONSE" if response is not None else "PREPARE_ONLY",
          "status":"PREPARED","quality_verified":False,"release_authorized":False}
    start=time.monotonic()
    try:
        if api is not None:
            raw=api.chat(role="planner",messages=messages,stats_role="sportscausal_initial_planner",
                         temperature=0.0,allow_degraded_fallback=False)
            content=str(raw.get("content") or "")
            (out/"planner_response.txt").write_text(content,encoding="utf-8")
            audit=audit_reader(raw) if audit_reader else {}
            write(out/"planner_call_audit.json",audit)
            check(raw.get("provider_mode") in ("real","openai_compatible") and raw.get("http_ok") is not False,
                  "nonreal or failed provider response")
            finish=str(audit.get("finish_reason") or raw.get("finish_reason") or "").lower()
            check(finish=="stop","incomplete or unconfirmed provider finish reason: "+finish)
            response=parse_response(content)
        if response is not None:
            write(out/"planner_proposal.json",response)
            result=validate_and_bind(template,evidence,response)
            write(out/"story_graph_bundle.json",result)
            if "candidate_edl" in result:
                write(out/"candidate_edl.json",result["candidate_edl"])
            meta["status"]=result["status"]
            meta["segments"]=len(result.get("candidate_edl",[]))
            meta["missing_required_slots"]=result.get("missing_required_slots")
    except Exception as exc:
        meta.update(status="FAILED",error=f"{type(exc).__name__}: {exc}")
    finally:
        meta["elapsed_sec"]=round(time.monotonic()-start,3)
        if api is not None and usage_reader is not None:
            meta["api_usage"]=usage_reader(api)
        else:
            meta["api_usage"]={"http_attempts":0,"est_cost_usd_real":0}
        write(out/"run_meta.json",meta)
    return meta

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("template","evidence","out-dir"):
        p.add_argument("--"+key,required=True)
    p.add_argument("--response-json",help="Offline fixture only, not a model prediction")
    p.add_argument("--allow-dev",action="store_true")
    p.add_argument("--enable-real-api",action="store_true")
    p.add_argument("--i-approve-budget",action="store_true")
    p.add_argument("--max-cost-usd",type=float)
    p.add_argument("--max-completion-tokens",type=int,default=4096)
    a=p.parse_args()
    t,e=read(a.template),read(a.evidence)
    check(e.get("schema")=="sportscausal_evidence_v2","Stage 1.2 evidence required")
    check(a.allow_dev or e.get("input_tier") in {"RAW_EVENTS_ONLY","INDEPENDENT_ATOMIC_ANNOTATED"},
          "development evidence requires --allow-dev")
    api=usage=audit=None
    if a.enable_real_api:
        check(a.i_approve_budget and number(a.max_cost_usd) and a.max_cost_usd>0
              and os.environ.get("STORY_API_ENABLE")=="1" and not a.response_json,
              "real call requires explicit budget and STORY_API_ENABLE=1")
        check(512<=a.max_completion_tokens<=8192,"invalid completion limit")
        root=Path(__file__).resolve().parents[2]/"11.20sstory_chain"
        sys.path[:0]=[str(root/"algo"),str(root/"eval")]
        from story_video_agent_v3.story_paid_eval import build_capped_provider,provider_usage,_call_audit_from_raw
        api=build_capped_provider(max_calls=1,max_cost_usd=a.max_cost_usd,
                                  max_completion_tokens=a.max_completion_tokens)
        usage,audit=provider_usage,_call_audit_from_raw
    response=read(a.response_json) if a.response_json else None
    meta=run(t,e,a.out_dir,api=api,response=response,usage_reader=usage,audit_reader=audit)
    print(json.dumps(meta,ensure_ascii=False,indent=2))
    return 1 if meta["status"]=="FAILED" else 0

if __name__=="__main__":
    raise SystemExit(main())
