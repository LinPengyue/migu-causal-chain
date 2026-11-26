"""R4/R5: common story-agent evidence and revision protocol.

The pure core is shared by fixture and real video execution. Model responses
are hypotheses; only observed, bounded source windows can enter a trial.
No benchmark labels, template classification, or causal-score ranking.
"""
from copy import deepcopy
from template_graph import check, number, known_nonlive, event_window

def valid_window(w,duration):
    return isinstance(w,list) and len(w)==2 and all(number(x) for x in w) and 0<=w[0]<w[1]<=duration

def overlaps(a,b):
    return a[0]<b[1] and b[0]<a[1]

def replay_windows(events,duration):
    return [w[0] for e in events if known_nonlive(e)
            for w in [event_window(e,duration)] if w]

def cut_identity(rows):
    return tuple((r["media_in"],r["media_out"]) for r in rows)

def seed_rows(graph,initial,legacy,evidence):
    if graph["agent_seed"]["file"]=="legacy_seed.json":
        check(isinstance(legacy,dict) and isinstance(legacy.get("edl"),list),"legacy native story plan required")
        # Scoreboard anchors in native candidate plan are context, not goal
        # actions. Historical include_in_cut=false is not render authorization.
        rows=[r for r in legacy["edl"] if r.get("shot_kind")=="live"]
        basis="legacy_action_candidate_preview"
    else:
        rows=initial
        basis="r3_anchor_preview"
    result=[]
    for i,r in enumerate(rows):
        w=[r["media_in"],r["media_out"]]
        check(valid_window(w,evidence["duration_sec"]),"seed source window invalid")
        result.append({**deepcopy(r),"segment_id":str(r["segment_id"]),"video_id":evidence["video_id"],
            "include_in_cut":True,"preview_only":True,"first_live_verified":False,
            "first_live_status":"NOT_VERIFIED","verification_status":"draft","seed_basis":basis,
            "story_node_ids":list(r.get("story_node_ids",[]))})
    check(bool(result),"empty seed")
    # Map by actual source window overlap, not legacy synthetic event IDs.
    for r in result:
        w=[r["media_in"],r["media_out"]]
        for n in graph["nodes"]:
            if n["node_type"]=="anchor" and any(overlaps(w,x) for x in n.get("media_windows",[])):
                if n["node_id"] not in r["story_node_ids"]:
                    r["story_node_ids"].append(n["node_id"])
    validate_cut(result,evidence["duration_sec"])
    return result

def validate_cut(rows,duration):
    seen=set(); end=0
    for r in rows:
        sid=r["segment_id"]; w=[r["media_in"],r["media_out"]]
        check(sid not in seen and valid_window(w,duration) and end<=w[0],"invalid or overlapping cut")
        seen.add(sid); end=w[1]

def task_windows(t,evidence,max_clip_sec):
    # Broad missing-action regions are tiled, never presented as a single
    # clip or silently truncated. The caller controls budget/selection.
    windows=[]
    if t.get("search_interval"):
        windows.append(t["search_interval"])
    windows.extend(t.get("media_windows",[]))
    for a in t.get("path_alternatives",[]):
        if a.get("media_windows"):
            windows.append([a["media_windows"][0][0],a["media_windows"][-1][1]])
    out=[]
    for w in windows:
        check(valid_window(w,evidence["duration_sec"]),"invalid task search window")
        lo,hi=w
        while lo<hi:
            end=min(hi,lo+max_clip_sec)
            out.append([lo,end])
            if end==hi: break
            lo=end-min(3,max_clip_sec/4)
    return list(dict.fromkeys(tuple(w) for w in out))

def inventory(evidence,lo,hi):
    return [{"event_id":a["event_id"],"t":a["t"],"window":a["window"],"type":a["type"],
             "notes":a.get("notes"),"attributes":a.get("attributes"),"scores":a.get("scores"),
             "chain_ids":[cid for cid,c in evidence["chains"].items() if a["event_id"] in c["available_event_ids"]]}
            for a in sorted(evidence["atoms"].values(),key=lambda a:(a["t"],a["event_id"]))
            if a.get("broadcast_phase")=="LIVE" and lo<=a["t"]<=hi]

def story_intervals(graph,evidence):
    anchors=[n for n in graph["nodes"] if n["node_type"] in {"anchor","missing"}]
    def bound(n):
        w=n.get("action_time_interval")
        if w: return w
        ws=n.get("media_windows",[])
        return [ws[0][0],ws[-1][1]] if ws else None
    result=[]
    for a,b in zip(anchors,anchors[1:]):
        x,y=bound(a),bound(b)
        if x and y and x[1]<y[0]:
            result.append({"interval_id":a["node_id"]+"->"+b["node_id"],"from":a["node_id"],"to":b["node_id"],"window":[x[1],y[0]]})
    # Tail is bounded by the next score transition when known, not entire
    # remainder of match for a short equalization story.
    if anchors:
        last=anchors[-1]; x=bound(last)
        if x:
            hi=evidence["duration_sec"]
            if graph["template_id"]=="equalization":
                # Unknown later score boundaries: defer tail proposals,
                # rather than attach unrelated late-match events.
                hi=x[1]
            if x[1]<hi:
                result.append({"interval_id":"tail:"+last["node_id"],"from":last["node_id"],"to":None,"window":[x[1],hi]})
    return result

def parse_hypotheses(raw,interval,events):
    check(isinstance(raw,dict) and isinstance(raw.get("hypotheses"),list) and len(raw["hypotheses"])<=5,
          "expected at most five story hypotheses")
    by={e["event_id"]:e for e in events}; result=[]
    for i,h in enumerate(raw["hypotheses"],1):
        ids=h.get("event_ids")
        check(isinstance(ids,list) and ids and len(ids)==len(set(ids)) and set(ids)<=set(by),
              "hypothesis references unknown event")
        check(ids==sorted(ids,key=lambda x:(by[x]["t"],x)),"hypothesis event order")
        check(isinstance(h.get("narrative_function"),str) and h["narrative_function"].strip()
              and isinstance(h.get("hypothesis"),str) and h["hypothesis"].strip(),"empty narrative hypothesis")
        result.append({"hypothesis_id":interval["interval_id"]+":h"+str(i),
                       "interval_id":interval["interval_id"],"event_ids":ids,
                       "hypothesis":h["hypothesis"],"narrative_function":h["narrative_function"],
                       "media_windows":[by[x]["window"] for x in ids],"causal_verified":False})
    return result

def validate_observation(raw,clip,source_sha,duration):
    check(isinstance(raw,dict) and raw.get("clip_id")==clip["clip_id"],"observation clip mismatch")
    check(raw.get("finding") in {"SUPPORTED","CONTRADICTED","UNCERTAIN"},"invalid observation verdict")
    check(isinstance(raw.get("description"),str) and raw["description"].strip(),"missing visual description")
    w=raw.get("action_window_sec")
    if w is not None:
        check(valid_window(w,duration) and clip["source_window"][0]<=w[0]<w[1]<=clip["source_window"][1],
              "observed action outside supplied clip")
    return {**deepcopy(raw),"source_sha256":source_sha,"clip_sha256":clip["sha256"],
            "source_window":clip["source_window"],"observation_method":"native_video_transcoded_5fps",
            "first_live_verified":False}

def trial_revision(rows,plan,observations,evidence,nonlive):
    action=plan.get("action")
    check(action in {"add","replace","trim","drop","keep"},"unsupported revision action")
    if action=="keep": return deepcopy(rows)
    target=plan.get("target_segment_id")
    r=next((x for x in rows if x["segment_id"]==target),None)
    if action!="add": check(r is not None,"unknown target segment")
    # Dropping a protected anchor requires a contradicted visual finding.
    obs=observations.get(plan.get("observation_id"))
    check(obs is not None,"revision missing observation")
    if action=="drop":
        check(obs["finding"]=="CONTRADICTED","drop without contrary visual evidence")
        check(overlaps([r["media_in"],r["media_out"]],obs["source_window"]),"drop observation unrelated to segment")
        check(not r.get("story_node_ids") or plan.get("anchor_overturn") is True,
              "protected anchor requires explicit overturn")
        new=[deepcopy(x) for x in rows if x["segment_id"]!=target]
    else:
        w=obs.get("action_window_sec")
        check(obs["finding"]=="SUPPORTED" and valid_window(w,evidence["duration_sec"]),
              "no supported observed action window")
        check(not any(overlaps(w,x) for x in nonlive),"observed window overlaps annotated replay")
        check(obs.get("broadcast")=="LIVE","clip not supported as live")
        if action=="trim":
            check(r["media_in"]<=w[0]<w[1]<=r["media_out"],"trim outside segment")
        ids=[eid for eid in obs.get("event_ids",[]) if eid in evidence["atoms"] and
             overlaps(w,evidence["atoms"][eid]["window"])]
        new=[deepcopy(x) for x in rows if action=="add" or x["segment_id"]!=target]
        new.append({"segment_id":target if action in {"trim","replace"} else "trial:"+str(plan["observation_id"]),
            "video_id":evidence["video_id"],"media_in":w[0],"media_out":w[1],"event_ids":ids,
            "story_node_ids":list(r.get("story_node_ids",[])) if r else list(obs.get("story_node_ids",[])),
            "role":r.get("role","context") if r else "context",
            "source_observation_id":plan["observation_id"],"include_in_cut":True,
            "preview_only":True,"first_live_verified":False,"first_live_status":"NOT_VERIFIED",
            "verification_status":"trial"})
    new.sort(key=lambda x:(x["media_in"],x["media_out"]))
    check(bool(new),"empty trial")
    validate_cut(new,evidence["duration_sec"])
    for i,x in enumerate(new,1): x.update(edl_index=i,narrative_order=i)
    return new

def verifier_decision(raw,changed,real_visual):
    if not real_visual or not changed:
        return "NOT_EVALUATED"
    check(isinstance(raw,dict) and raw.get("decision") in {"ACCEPT","REJECT","UNCERTAIN"},
          "invalid verifier decision")
    check(isinstance(raw.get("rationale"),str) and raw["rationale"].strip(),"missing verifier rationale")
    if raw["decision"]=="ACCEPT":
        check(raw.get("original_issue_resolved") is True and raw.get("new_defect") is False
              and isinstance(raw.get("before_evidence"),str) and raw["before_evidence"].strip()
              and isinstance(raw.get("after_evidence"),str) and raw["after_evidence"].strip(),
              "accept without comparative evidence")
    return raw["decision"]
