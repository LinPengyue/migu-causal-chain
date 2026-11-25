"""V3-R-General R1: conservative role-specific normalization of Stage 1.2 evidence.

Annotation claims, not independent visual facts. No reference or model access.
"""
from __future__ import annotations

import re
from template_graph import check

SIDE = r"(?<![A-Za-z0-9_])team_[12](?![0-9])|[12一二]队"
KEEPER = r"(?:守门员|门将|goalkeeper)"
RESCUE = r"(?:扑救|扑住|扑出|扑飞|扑到|扑球|抱住|接住|托出|挡出|拦截|解围|顶出|打出|推出|救险|救球|封堵|踢走|化解|防住)"
SHOT = r"(?:射门|打门|打球门|攻门|起脚|远射|抽射|头球攻门)"
SET_PIECE = r"(?:发出角球|发角球|开角球|发任意球|直发任意球|开任意球|主罚|发球|开出|角球|任意球)"
GOAL = r"(?:破门|进球|打进|踢进|射入|头球得分)"
SCORE = re.compile(r"\s*(\d+)\s*[:：]\s*(\d+)\s*")
BAD = re.compile(r"未能|没有|没能|未成功|失败|试图|尝试扑救|扑救未果|无效扑救")

def values(a, key):
    v=(a.get("attributes") or {}).get(key)
    return v if isinstance(v,list) else [v] if isinstance(v,str) else []

class Roles:
    def __init__(self, teams):
        aliases={"team_1":"team_1","1队":"team_1","一队":"team_1",
                 "team_2":"team_2","2队":"team_2","二队":"team_2"}
        for side in ("team_1","team_2"):
            name=((teams or {}).get(side) or {}).get("name")
            if isinstance(name,str) and name.strip():
                if name in aliases and aliases[name]!=side:
                    continue
                aliases[name]=side
        self.aliases=aliases
        self.side=r"(?:"+ "|".join(re.escape(x) for x in sorted(aliases,key=len,reverse=True))+r")"
        # Keep role immediately attached to the team or player number. Do not
        # infer the actor from a mention in a neighboring event or a color alone.
        self.keeper=re.compile(r"(?P<side>"+self.side+r")\s*(?:(?P<num1>\d{1,2})号\s*)?"+KEEPER+r"(?:\s*(?P<num2>\d{1,2})号)?")
        self.ref=re.compile(r"^(?P<side>"+self.side+r")(?:(?:_player_)(?P<n1>\d{1,2})|(?:(?P<n2>\d{1,2})号)?(?:球员|队员|守门员|门将)?(?:(?P<n3>\d{1,2})号)?)$")
        # A bounded same-clause action span; stop at another named subject.
        tail=r"(?:(?!"+self.side+r"|[，。；！？,;.!?]).){0,24}?"
        self.keeper_action=re.compile(self.keeper.pattern+r"(?!\s*(?:的|被))"+tail+RESCUE+r"(?:失败|未果)?")
        self.shot_action=re.compile(r"(?P<side>"+self.side+r")\s*(?:(?P<num>\d{1,2})号)?(?:球员|队员)?"+tail+SHOT)
        # A same-note coordinated clause may omit the subject, but only accept
        # an explicit continuation verb (e.g. "看到进攻机会，选择打门").
        # No inheritance across event rows.
        self.shot_continuation=re.compile(r"(?P<side>"+self.side+r")\s*(?:(?P<num>\d{1,2})号)?(?:球员|队员)?"+tail+
                                          r"[，,]\s*(?:选择|随后|接着|直接|顺势|然后|立即|随即)"+SHOT)
        self.shot_object=re.compile(r"(?P<side>"+self.side+r")\s*(?:\d{1,2}号)?(?:球员|队员)?(?:的)?"+tail+SHOT)
        # Bounded subject-action spans. The set-piece predicate must describe
        # an execution, not a player conceding a corner or free kick.
        subject=r"(?P<side>"+self.side+r")\s*(?:(?P<num>\d{1,2})号)?(?:球员|队员)?"
        self.set_piece_action=re.compile(subject+tail+SET_PIECE)
        self.goal_action=re.compile(subject+tail+GOAL)
        self.team_re=re.compile(self.side)

    def claims(self,a,keys):
        out=[]
        for k in keys:
            for v in values(a,k):
                if not isinstance(v,str):
                    continue
                m=self.ref.fullmatch(v.strip())
                if m:
                    out.append({"team":self.aliases[m["side"]],"player":m["n1"] or m["n2"] or m["n3"],
                                "keeper_explicit":bool(re.search(KEEPER,v)),
                                "source":"attributes."+k,"text":v})
        return out

    def note_claims(self,a,pattern,*,keeper=False,execution=False):
        note=a.get("notes") or ""
        if not isinstance(note,str):
            return []
        out=[]
        for m in pattern.finditer(note):
            phrase=m.group()
            # A failure/attempt anywhere in this clause invalidates the positive
            # rescue claim. Unknown is retained for later inspection.
            left=max(note.rfind(p,0,m.start()) for p in "，。；！？,;.!?")+1
            stops=[note.find(p,m.end()) for p in "，。；！？,;.!?" if note.find(p,m.end())>=0]
            right=min(stops) if stops else len(note)
            if keeper and BAD.search(note[left:right]):
                continue
            if execution:
                # Possessive/passive/awarded-to-opponent mentions are not
                # positive actor evidence. Keep explicit clauses separable.
                if re.search(r"被罚|被判|送给|送出|造成|获得|赢得|被破门|被进球|未能|没能|进球无效|取消进球|越位在先",phrase):
                    continue
                if re.search(r"^(?:的|被)",phrase[len(m["side"]):]):
                    continue
            d=m.groupdict()
            out.append({"team":self.aliases[m["side"]],"player":d.get("num1") or d.get("num2") or d.get("num"),
                        "keeper_explicit":keeper,"source":"notes.role_action","text":phrase})
        return out

def resolve(claims):
    sides=sorted({c["team"] for c in claims})
    players=sorted({c["player"] for c in claims if c["player"]})
    return {"team":sides[0] if len(sides)==1 else None,
            "team_status":"EXPLICIT" if len(sides)==1 else "CONFLICT" if sides else "UNRESOLVED",
            "player_number":players[0] if len(sides)==1 and len(players)==1 else None,
            "player_status":"CONFLICT" if len(players)>1 or len(sides)>1 else "EXPLICIT" if players else "UNRESOLVED",
            "claims":claims}

def normalize_atom(a,roles):
    typ=a.get("type")
    note=a.get("notes") or ""
    keeper_claims=[]
    if typ in {"Save","Goal_line_clearance","Defensive_action"}:
        note_keeper=roles.note_claims(a,roles.keeper_action,keeper=True)
        attrs=roles.claims(a,["Defender"] if typ=="Defensive_action" else ["Related_Player","Defender"])
        explicit=[c for c in attrs if c["keeper_explicit"]]
        # A Save denotes a goalkeeper action, but only an explicit role-bound
        # attribute or action note supplies the team. For defensive events a
        # keeper mention without a rescue action is not enough.
        if note_keeper or (explicit and typ in {"Save","Goal_line_clearance"} and not BAD.search(note)):
            keeper_claims=note_keeper+attrs
        elif typ=="Defensive_action" and explicit and not BAD.search(note):
            kinds=set(values(a,"Defensive_Action")) | {a.get("label")}
            if kinds.intersection({"Goal_line_Incident","Clearance","Interception"}) and re.search(RESCUE,note):
                keeper_claims=explicit
    keeper=resolve(keeper_claims)
    shot_claims=[]
    if typ=="Shot":
        shot_claims=(roles.note_claims(a,roles.shot_action)+roles.note_claims(a,roles.shot_continuation)
                     +roles.claims(a,["BallController_player","BallController_team"]))
        # Related_Player is not generally the shooter; do not use it blindly.
    shooter=resolve(shot_claims)
    execution_claims=[]
    if typ in {"Corner_kick","Free_kick","Penalty"}:
        execution_claims=roles.note_claims(a,roles.set_piece_action,execution=True)
        execution_claims+=roles.claims(a,["BallController_player","BallController_team","Related_Player"])
    elif typ=="Goal" and not re.search(r"乌龙|进球无效|取消进球|越位在先",note):
        execution_claims=roles.note_claims(a,roles.goal_action,execution=True)
        execution_claims+=roles.claims(a,["BallController_player","BallController_team"])
    execution=resolve(execution_claims)
    threat_claims=list(shot_claims)
    # Explicit attacking role in a rescue; only use an opposing team and
    # never promote generic nearby possession to an attack.
    if keeper["team"]:
        attackers=roles.claims(a,["Attacker"])
        shot_mentions=roles.note_claims(a,roles.shot_object)
        # The keeper's own action phrase cannot be the opponent's shot.
        opposing=[c for c in attackers+shot_mentions if c["team"]!=keeper["team"]]
        # For a note-only Save, a role-bound attacker phrase is required.
        threat_claims=opposing
    threat=resolve(threat_claims)
    predicates={}
    live=(a.get("broadcast_phase")=="LIVE")
    if live and keeper["team"]:
        predicates["goalkeeper_rescue"]={"actor":keeper["team"],"basis":"explicit_keeper_action"}
    if live and threat["team"]:
        predicates["attacking_threat"]={"actor":threat["team"],"basis":"shot_attempt" if typ=="Shot" else "opposition_to_keeper_rescue"}
    if live and execution["team"]:
        if typ in {"Corner_kick","Free_kick","Penalty"}:
            predicates["set_piece_execution"]={"actor":execution["team"],"basis":"role_bound_restart"}
        elif typ=="Goal":
            predicates["goal_action"]={"actor":execution["team"],"basis":"role_bound_goal_annotation"}
    score=(a.get("scores") or {}).get("score_recognition")
    sm=SCORE.fullmatch(score) if isinstance(score,str) else None
    return {"event_id":a["event_id"],"t":a["t"],"window":a["window"],"type":typ,
            "broadcast_phase":a.get("broadcast_phase"),"keeper":keeper,"shooter":shooter,
            "attacking_team":threat,"execution_actor":execution,"predicates":predicates,
            "score_observation":[int(sm[1]),int(sm[2])] if sm else None,
            "notes":note,"attributes":a.get("attributes"),"enrichment_provenance":a.get("enrichment_provenance")}

def normalize(evidence):
    check(evidence.get("schema")=="sportscausal_evidence_v2","Stage 1.2 evidence required")
    roles=Roles(evidence.get("teams"))
    atoms=[normalize_atom(a,roles) for a in sorted(evidence["atoms"].values(),key=lambda x:(x["t"],x["event_id"]))]
    return {"schema":"v3r_general_semantics_v1","video_id":evidence["video_id"],
            "input_tier":evidence["input_tier"],"teams":evidence.get("teams"),"atoms":atoms,
            "scope":"single_source_annotation_claims_not_visual_verification"}
