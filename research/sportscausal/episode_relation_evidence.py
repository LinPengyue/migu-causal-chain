"""R2a.3: original ordered membership is evidence, not causal truth."""
from collections import defaultdict

def chain_edges(evidence,by):
    out=defaultdict(list)
    for cid,c in sorted(evidence["chains"].items()):
        if c.get("state") not in {"FULL","PARTIAL"}:
            continue
        ids=c.get("event_ids")
        if not ids and c["state"]=="FULL":
            ids=c.get("available_event_ids",[])
        if not ids or len(ids)!=len(set(ids)):
            continue
        avail=set(c.get("available_event_ids",[]))
        for x,y in zip(ids,ids[1:]):
            if x in avail and y in avail and x in by and y in by:
                out[(x,y)].append({"chain_id":cid,"state":c["state"],"subtype":c.get("subtype")})
    return out
