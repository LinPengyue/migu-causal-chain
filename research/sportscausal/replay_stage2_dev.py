"""Zero-HTTP replay of the persisted Stage 2 development request.

Only the already-exposed compact event and predicted-chain tables are read.
This is not a formal benchmark input, and cannot establish first-live status.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from template_graph import check, read, write
from semantic_normalization import normalize
from temporal_patterns import match

def restore(messages):
    check(isinstance(messages,list),"expected recorded message list")
    request=json.loads(next(m["content"] for m in messages if m["role"]=="user"))
    source=request["source"]
    check(source["input_tier"]=="HUMAN_ATOM_ENRICHED_DEV","historical DEV artifact required")
    atoms={}
    for row in request["events"]:
        check(len(row)==len(request["event_columns"]),"event row/column mismatch")
        a=dict(zip(request["event_columns"],row))
        eid=a["event_id"]
        check(eid not in atoms,"duplicate event")
        atoms[eid]=a
    chains={}
    for row in request["predicted_chains"]:
        check(len(row)==len(request["chain_columns"]),"chain row/column mismatch")
        c=dict(zip(request["chain_columns"],row))
        cid=c["chain_id"]
        check(cid not in chains and c["availability"] in {"FULL","PARTIAL"} and
              all(e in atoms for e in c["available_event_ids"]),"invalid recorded chain")
        chains[cid]={"chain_id":cid,"state":c["availability"],"subtype":c["subtype"],
                     "category":c["category"],"available_event_ids":c["available_event_ids"],
                     "causal_verified":False}
    return {"schema":"sportscausal_evidence_v2",**source,"atoms":atoms,"chains":chains,
            "first_live_verified":False,"source_limit":"recorded Stage 2 compact DEV request"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--messages",required=True)
    p.add_argument("--out-dir",required=True)
    p.add_argument("--allow-dev",action="store_true")
    a=p.parse_args()
    check(a.allow_dev,"explicit DEV authorization required")
    e=restore(read(a.messages))
    s=normalize(e)
    out=Path(a.out_dir)
    out.mkdir(parents=True,exist_ok=False)
    write(out/"normalized_semantics.json",s)
    summary={"input_tier":e["input_tier"],"n_atoms":len(e["atoms"]),
             "n_context_chains":len(e["chains"]),"http_calls":0,
             "quality_verified":False,"first_live_verified":False,"patterns":{}}
    for name in ("keeper_rescue","alternating_threats","set_piece_breakthrough"):
        template=read(Path(__file__).parent/"patterns"/(name+".json"))
        r=match(template,s,e)
        write(out/(name+".json"),r)
        summary["patterns"][name]={"n_predicate_events":r["n_predicate_events"],
                                   "n_candidates":len(r["candidates"]),
                                   "subjects":[c["subjects"] for c in r["candidates"]]}
    write(out/"summary.json",summary)
if __name__=="__main__":
    main()
