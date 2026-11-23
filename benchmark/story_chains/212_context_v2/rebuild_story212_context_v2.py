#!/usr/bin/env python3
"""Source-grounded story reconstruction. No vision / no claims of gold verification.

A story is assembled from a meaningful game-wide narrative and relevant nearby actions,
not from a fixed 5-beat template. Never fabricate timestamps, goals, relations or FIRST_LIVE.
"""
import collections, csv, json, math, re, zipfile, os, hashlib, statistics
from pathlib import Path
ROOT=Path('/mnt/data')
OUT=ROOT/'StoryChain_212_Context_Rebuild'
OUT.mkdir(exist_ok=True)
(OUT/'matches').mkdir(exist_ok=True)
roster=json.loads((ROOT/'.story_source_index.json').read_text(encoding='utf-8'))['roster']
old=json.loads((ROOT/'StoryChain_212_Public_Format/story_chains_212.json').read_text(encoding='utf-8'))['story_chains']
assert len(old)==212
by_match=collections.defaultdict(list)
for row in old: by_match[row['match_id']].append(row)
used_archives=sorted({src['archive'] for m in roster for src in m['matches']})
ZIP={k:zipfile.ZipFile(ROOT/k) for k in used_archives}
cache={}
def read(src):
 k=(src['archive'],src['path'])
 if k not in cache:cache[k]=json.loads(ZIP[k[0]].read(k[1]).decode('utf-8-sig'))
 return cache[k]
def text(x):return str(x or '').strip()
def num(x):
 try:
  x=float(x)
  return round(x,3) if math.isfinite(x) and 0<=x<=25000 else None
 except (TypeError,ValueError):return None
def timeval(ev):return num((ev.get('media_time') or {}).get('event_time_sec'))
def window(ev):
 mt=ev.get('media_time') or {}; a=num(mt.get('start_time_sec'));b=num(mt.get('end_time_sec'))
 return (a,b) if a is not None and b is not None and 0<b-a<=180 else None
def chainwindow(c):
 s=text(c.get('segment_time_video')).translate(str.maketrans({'：':':','—':'-','－':'-','–':'-','至':'-'}))
 m=re.findall(r'(?<!\d)(\d{1,3}):(\d{2})(?!\d)',s)
 if len(m)==2 and all(int(x[1])<=59 for x in m):
  a=int(m[0][0])*60+int(m[0][1]);b=int(m[1][0])*60+int(m[1][1]);
  if 0<b-a<=150:return a,b
 m=re.fullmatch(r'\s*(\d{1,3}):(\d{2})\s*-+\s*(\d{2})\s*',s)
 if m and int(m[2])<60 and int(m[3])<60:
  a=int(m[1])*60+int(m[2]);b=int(m[1])*60+int(m[3]);
  if b>a:return a,b
 return None
def usable(ev):
 # Annotation LIVE metadata can be wrong for TV replays and cross-match montages.
 note=text(ev.get('notes'))
 if re.search(r'回放|重播|比赛集锦|精彩集锦|进球集锦|进球回顾|赛事回顾|慢镜头|历史镜头|精彩瞬间',note,re.I):return False
 return True
def live(ev):
 v=ev.get('video_context') or {}
 return v.get('is_replay') is False and v.get('is_slow_motion') is not True and text(v.get('broadcast_phase')).upper() in ('LIVE','FIRST_LIVE') and usable(ev)
def attrs(e,k):
 v=(e.get('attributes') or {}).get(k)
 if isinstance(v,list): return [text(y) for y in v if text(y)]
 return [text(v)] if text(v) else []
def score(e):
 v=(e.get('scores') or {}).get('score_recognition')
 if not v:v=attrs(e,'Score_Recognition')
 if isinstance(v,list):v=v[0] if v else ''
 m=re.search(r'(?<!\d)(\d{1,2})\s*[:：]\s*(\d{1,2})(?!\d)',text(v))
 if not m:return None
 a,b=map(int,m.groups());return f'{a}:{b}' if a<=20 and b<=20 else None
TEAM1=re.compile(r'(?:一队|1\s*队|主队)',re.I)
TEAM2=re.compile(r'(?:二队|2\s*队|客队)',re.I)
def team_from_string(s):
 if TEAM1.search(s) and not TEAM2.search(s):return 'team_1'
 if TEAM2.search(s) and not TEAM1.search(s):return 'team_2'
 if TEAM1.search(s):return 'team_1' if TEAM1.search(s).start() < TEAM2.search(s).start() else 'team_2'
 return None
def team_of(e):
 v=attrs(e,'BallController_team')
 if v and v[0] in ('team_1','team_2'):return v[0]
 n=text(e.get('notes'))
 return team_from_string(n)
def goalkeeper_team(e):
 if text(e.get('event_type')).lower() not in ('save','goal_line_clearance'):return None
 n=text(e.get('notes'))
 # Bind the closest team mention immediately before the keeper term.
 for keeper in re.finditer(r'守门员|门将',n):
  precede=n[max(0,keeper.start()-24):keeper.start()]
  hits=list(re.finditer(r'([一二12]\s*队)',precede))
  if hits:
   nearest=hits[-1]
   if len(precede)-nearest.end()<=7:return team_from_string(nearest.group(1))
  follow=n[keeper.end():keeper.end()+10]
  aft=re.search(r'([一二12]\s*队)',follow)
  if aft:return team_from_string(aft.group(1))
 # If a shot team is explicit, save is by the opponent; require shot and save words.
 m=re.search(r'([一二12]\s*队).{0,15}(?:射门|攻门|打门|头球)',n)
 if m and re.search(r'扑救|扑出|挡出|封堵',n):
  t=team_from_string(m.group(1));return {'team_1':'team_2','team_2':'team_1'}.get(t)
 return None
def who(e):
 n=text(e.get('notes'))
 t=text(e.get('event_type')).lower()
 # In goal records, BallController_player can be an assister! Prefer explicit scorer in notes.
 if t in ('goal','penalty_goal','header_goal'):
  m=re.search(r'([一二12]\s*队)\s*(\d{1,2})号.{0,14}(?:射门|头球|倒钩|凌空|推射|低射|补射).{0,6}(?:进球|破门|打进|入网)',n)
  if m:
   team=team_from_string(m[1]);return f'{team}_player_{m[2]}' if team else None
  m=re.search(r'([一二12]\s*队)\s*(\d{1,2})号.{0,36}(?:接|受到|摆脱|挣顶|争顶|直接|门前).{0,24}(?:破门|进球)',n)
  if m:
   team=team_from_string(m[1]);return f'{team}_player_{m[2]}' if team else None
  m=re.search(r'([一二12]\s*队).*?([一二12]?\s*队)?(\d{1,2})号(?:头球|射门|推射|补射).{0,6}(?:进球|破门|入网)',n)
  if m:
   team=team_from_string(m[2]) if m[2] else team_from_string(m[1]);return f'{team}_player_{m[3]}' if team else None
  return None
 vals=attrs(e,'BallController_player')
 if vals and re.search(r'(?:team_[12]_player_\d+)',vals[0]):return vals[0]
 m=re.search(r'([一二12]\s*队)\s*(\d{1,2})\s*号',n)
 if m:
  team=team_from_string(m[1]);return f'{team}_player_{m[2]}' if team else None
 return None
def quality(x):
 if x['kind']=='chain':
  st=x['subtype'];return 92 if ('进球' in st or '红牌' in st or 'VAR' in st or '改判' in st) else 76
 t=x['typ'];e=x['raw'];q={'goal':110,'penalty_goal':110,'save':80,'goal_line_clearance':79,'shot':55,'header_shot':55,'assist':72,'video_assistant_referee':90,'referees_decision':70,'receive_a_card':67,'controversy':68,'corner_kick':51,'free_kick':49,'foul_being_fouled':44,'defensive_action':44,'dribble_past':40,'pass':25,'full_time':50,'substitution':25,'penalty_':82,'ball_possession':18,'throw_in':15}.get(t,15)
 ar=e.get('attributes') or {}
 if t=='shot':
  val=' '.join(attrs(e,'Shot_Result')).lower()
  q+=18 if 'post' in val or 'crossbar' in val or 'on_target' in val else 0
 if t=='receive_a_card':
  if 'red' in ' '.join(attrs(e,'Card_Type')).lower():q+=38
 if t=='pass':
  if re.search('传中|直塞|身后|反击|配合|过顶|横传',text(e.get('notes'))):q+=16
 if text(e.get('notes')) not in ('','1','无'):q+=4
 for metric in ('criticality_score','emotional_heat_score'):
  v=(e.get('scores') or {}).get(metric)
  try:q+=min(5,max(0,float(v)-1))
  except (TypeError,ValueError):pass
 return q

def event_name(x):
 e=x['raw']; s=text(e.get('event_type_zh')) or text(e.get('event_type'))
 note=text(e.get('notes'))
 note=re.sub(r'\s+',' ',note)
 if note in ('1','无','未知','没有','-'):note=''
 if len(note)>85:note=note[:82]+'…'
 return f'{s}：{note}' if note else s

def chain_name(x):
 c=x['raw'];ss=text(c.get('causal_chain_subtype')) or text(c.get('causal_chain_other_name')) or '短程因果链'
 ts=[text(e.get('type')) for e in c.get('events',[]) if isinstance(e,dict) and text(e.get('type'))]
 if ts:
  ts=list(dict.fromkeys(ts));return f'{ss}（{" → ".join(ts[:4])}）'
 return ss

def record(x,role,func,relation,importance):
 b={'segment_id':None,'order':None,'narrative_role':role,'narrative_function':func,
    'description':event_name(x) if x['kind']=='event' else chain_name(x),
    'source_type':'source_event' if x['kind']=='event' else 'source_chain',
    'source_id':x['id'],'start_sec':x['start'],'end_sec':x['end'],
    'source_archive':x['archive'],'source_json_path':x['path'],
    'source_video_name':x['video'],'importance':importance}
 if relation:b['relation_to_previous']=relation
 if x.get('score') and x['kind']=='event':b['score_observed']=x['score']
 if x['kind']=='chain':b['source_time_basis']='linked_event_bz_id_media_time'
 return b

def source_sort(s):
 name=os.path.basename(s['path']);m=re.search(r'(?:^|[^0-9])\d{2}_([12])\s',name)
 return (int(m[1]) if m else 0,name)

def populate(match):
 srcs=match['matches'];evsrc=[s for s in srcs if s['kind']=='event'];chsrc=[s for s in srcs if s['kind']=='chain']
 if evsrc:
  pri=min(s['priority'] for s in evsrc);evsrc=sorted([s for s in evsrc if s['priority']==pri],key=source_sort)
 if chsrc:
  pri=min(s['priority'] for s in chsrc);chsrc=sorted([s for s in chsrc if s['priority']==pri],key=source_sort)
 streams=[];teams={}
 for k,s in enumerate(evsrc):
  d=read(s);teams.update({i:(d.get('teams') or {}).get(i,{}).get('name') for i in ('team_1','team_2') if (d.get('teams') or {}).get(i,{}).get('name')})
  v=text((d.get('video') or {}).get('file_name')) or s['path'][:-5]+'.mp4'
  stream={'idx':k,'path':s['path'],'archive':s['archive'],'video':v,'duration_sec':num((d.get('video') or {}).get('duration_sec')),'clip_base':os.path.splitext(os.path.basename(s['path']))[0],'ev':[],'chs':[]}
  for e in d.get('events',[]):
   if not isinstance(e,dict) or not live(e) or not text(e.get('event_id')):continue
   win=window(e)
   if not win:continue
   typ=text(e.get('event_type')).lower();t=timeval(e)
   if t is None: t=(win[0]+win[1])/2
   x={'kind':'event','raw':e,'id':str(e['event_id']),'idx':k,'archive':s['archive'],'path':s['path'],'video':v,'clip_base':os.path.splitext(os.path.basename(s['path']))[0], 'start':win[0],'end':win[1],'t':t,'typ':typ,'team':team_of(e),'keeper_team':goalkeeper_team(e),'actor':who(e),'score':score(e)}
   x['q']=quality(x);stream['ev'].append(x)
  stream['ev'].sort(key=lambda y:y['t']);streams.append(stream)
 # Match chain source with its corresponding event clip by base name, not by differing event IDs.
 for s in chsrc:
  d=read(s);key=re.sub(r'_causal$','',os.path.splitext(os.path.basename(s['path']))[0]);matched=next((st for st in streams if st['clip_base']==key),None)
  if not matched:continue
  event_by_bz={e['raw'].get('bz_id'):e for e in matched['ev'] if e['raw'].get('bz_id')}
  for c in d.get('causal_chains',[]):
   if not isinstance(c,dict) or c.get('is_replay') is not False or len(c.get('events') or [])<2 or not text(c.get('annotation_id')):continue
   linked=[event_by_bz.get(v.get('bz_id')) for v in c['events']]
   # Always join using bz_id, never chain-internal event_id or segment_time_video.
   if not all(linked):continue
   win=(min(v['start'] for v in linked),max(v['end'] for v in linked))
   if not 0<win[1]-win[0]<=120:continue
   if matched['duration_sec'] and win[1]>matched['duration_sec']+2:continue
   x={'kind':'chain','raw':c,'id':str(c['annotation_id']),'idx':matched['idx'],'archive':s['archive'],'path':s['path'],'video':matched['video'],'clip_base':matched['clip_base'],'source_time_basis':'CHAIN_BZ_ID_LINKED_EVENT_MEDIA_TIME','linked':linked,'start':win[0],'end':win[1],'t':(win[0]+win[1])/2, 'typ':'short_chain','subtype':text(c.get('causal_chain_subtype')) or text(c.get('causal_chain_other_name')),'team':None,'keeper_team':None,'actor':None,'score':None}
   x['q']=quality(x)
   matched['chs'].append(x)
 for st in streams:
  # Find near-overlapping representative team from explicit action annotation when possible.
  for c in st['chs']:
   nearby=[e for e in st['ev'] if abs(e['t']-c['t'])<max(20,(c['end']-c['start'])/2+10) and e['typ'] in ('goal','shot','save','corner_kick','free_kick','defensive_action') and e['team']]
   if nearby:
    nearby.sort(key=lambda e:(abs(e['t']-c['t']),-e['q']))
    c['team']=nearby[0]['team']
  st['chs'].sort(key=lambda y:y['t'])
 return streams,teams

def distance(a,b):
 return (a['idx']-b['idx'])*100000 + a['t']-b['t'] if a['idx']==b['idx'] else 999999

def delta(a,b):return abs(a['t']-b['t']) if a['idx']==b['idx'] else math.inf

def nondup_add(bucket,x,tag='support'):
 k=(x['kind'],x['archive'],x['path'],x['id'])
 if any(v[1]['kind']==x['kind'] and (v[1]['archive'],v[1]['path'],v[1]['id'])==(x['archive'],x['path'],x['id']) for v in bucket):return
 bucket.append((tag,x))

def diverse(items,n=5,gap=55):
 ordered=sorted(items,key=lambda x:(-x['q'],x['idx'],x['t']));ans=[]
 for x in ordered:
  if any(x['idx']==p['idx'] and abs(x['t']-p['t'])<gap for p in ans):continue
  ans.append(x)
  if len(ans)>=n:break
 return sorted(ans,key=lambda x:(x['idx'],x['t']))

def filtergoal(ev):
 # Source may annotate several broadcasts of one scoring action as LIVE; dedup nearby identity/score.
 arr=sorted([x for x in ev if x['typ'] in ('goal','penalty_goal','header_goal') and not re.search(r'无效|取消|越位.*进球|进球.*越位|判定.*无效|被吹',text(x['raw'].get('notes')))],key=lambda z:(z['idx'],z['t']))
 out=[]
 for x in arr:
  if any(x['idx']==y['idx'] and x['t']-y['t']<130 and ((x['actor'] is not None and x['actor']==y['actor']) or (x['score'] is not None and x['score']==y['score'])) for y in out):continue
  out.append(x)
 return out

def isthreat(x):return x['typ'] in ('shot','header_shot','save','goal_line_clearance','goal','penalty_goal','header_goal')
def issetpiece(x):return x['typ'] in ('corner_kick','free_kick','penalty_')
def isbuild(x):
 if x['typ'] in ('assist','dribble_past','defensive_action','corner_kick','free_kick','foul_being_fouled'):return True
 return x['typ']=='pass' and x['q']>=42

def context_core(anchor,ev,bucket,mode='goal',span_pre=180,span_post=135):
 cand=[e for e in ev if e['idx']==anchor['idx'] and e['id']!=anchor['id'] and anchor['t']-span_pre <=e['t']<=anchor['t']+span_post]
 # Same match/period, no ungrounded cross-half interval.
 before=sorted((e for e in cand if e['t']<anchor['t']-15 and (isthreat(e) or isbuild(e))),key=lambda e: (-e['q'],-e['t']))
 near=sorted((e for e in cand if abs(e['t']-anchor['t'])<=32 and (isthreat(e) or isbuild(e))),key=lambda e:(-e['q'],abs(e['t']-anchor['t'])))
 after=sorted((e for e in cand if e['t']>anchor['t']+20 and e['t']<=anchor['t']+span_post and (isthreat(e) or isbuild(e) or e['typ']=='full_time')),key=lambda e:(-e['q'],e['t']))
 def eligible(e):
  if mode in ('setpiece','counter'):
   if e['team'] and anchor.get('team') and e['team']!=anchor['team'] and e['typ'] in ('shot','goal','corner_kick','free_kick','assist'):return False
  return True
 for x in before[:8]:
  if eligible(x) and (not any(delta(x,b[1])<35 for b in bucket)):
   nondup_add(bucket,x,'setup');break
 for x in near[:8]:
  if eligible(x) and (not any(delta(x,b[1])<17 for b in bucket)):
   nondup_add(bucket,x,'development');break
 for x in after[:8]:
  if (not any(delta(x,b[1])<35 for b in bucket)):
   nondup_add(bucket,x,'aftermath');break

def strong_score(ev):
 groups=collections.defaultdict(list)
 for e in ev:
  if e['score']:groups[e['idx']].append(e)
 out=[]
 for g in groups.values():
  last=None
  for e in sorted(g,key=lambda z:z['t']):
   if e['score']!=last:
    out.append(e);last=e['score']
 return out

def title_action(x):
 if not x:return ''
 if x['kind']=='chain':
  related=x.get('linked') or []
  # A chain is more informative than its class name when the underlying event has a real action note.
  candidates=[v for v in related if v['typ'] in ('goal','video_assistant_referee','receive_a_card','shot','save','referees_decision')]
  for v in reversed(candidates):
   note=text(v['raw'].get('notes'))
   if 4<=len(note)<=64 and not re.search('集锦|回放',note):return note
  return x.get('subtype') or '关键回合'
 note=text(x['raw'].get('notes'))
 if 3<=len(note)<=52 and not note.isnumeric():return note
 return text(x['raw'].get('event_type_zh')) or text(x['raw'].get('event_type'))

RENAMES={
 '判罚改写（待核）':'判罚争议与战局转折',
 '红牌人数变化（待核）':'红牌冲击与攻守重构',
 '定位球破门回合（短链候选）':'定位球战术执行与破局',
 '反击/失误破门回合（短链候选）':'攻守转换与关键破门',
 'T1 逆风翻盘':'逆风翻盘','T2 领先守成':'领先守成','T3 落后追平':'落后追平',
 'T4 比分拉锯':'比分拉锯','T5 末段制胜':'末段制胜','T6 大比分完胜':'大比分完胜',
 'T7 苦守保平':'苦守保平','T8 点球大战决胜':'点球大战决胜'}
EVENT_SPECIAL={'判罚争议与战局转折':{'video_assistant_referee','referees_decision','controversy'},
 '红牌冲击与攻守重构':{'receive_a_card'},
 '定位球战术执行与破局':{'corner_kick','free_kick'},
 '攻守转换与关键破门':{'defensive_action','shot','goal'}}

def build_story(oldstory,streams,teams,match_name):
 subtype=RENAMES.get(oldstory['story_chain_subtype'],oldstory['story_chain_subtype'])
 cate=oldstory['chain_category']
 if cate=='关键情节候选':cate='关键转折故事链'
 elif cate=='战术故事链':cate='攻防战术故事链'
 events=[x for st in streams for x in st['ev']];chains=[x for st in streams for x in st['chs']]
 goals=filtergoal(events);saves=[x for x in events if x['typ'] in ('save','goal_line_clearance')];threats=[x for x in events if isthreat(x)];score_marks=strong_score(events)
 bucket=[];issues=[];protag=None;headline=None;main=None;focus=[];outcome=None
 def add(x,tag='support'):
  if x is not None:nondup_add(bucket,x,tag)
 def teamname(t):return teams.get(t) or t if t else None
 def attach(anchor,mode,pre=180,post=135):
  if anchor:context_core(anchor,events,bucket,mode=mode,span_pre=pre,span_post=post)
 if cate=='战局故事链':
  # Anchor narrative in actual marked goals, not scoreboard-only observations.
  if goals:
   if len(goals)<=6:chosen=goals
   else:
    ids=[0,1,len(goals)//2,len(goals)-2,len(goals)-1]
    chosen=list(dict((goals[i]['id']+'_'+str(goals[i]['idx']),goals[i]) for i in ids).values())
   for x in chosen: add(x,'core');attach(x,'goal',185,155)
   main=chosen[-1]
  else:
   issues.append('未找到有可信时间区间的非回放进球标注，不应据类别声称翻盘/绝杀')
  if len(score_marks)>1:
   for x in (score_marks[:1]+score_marks[-1:]):
    if x['typ'] not in ('pass','ball_possession','throw_in','kick_off'):add(x,'score_context')
  # Fallback to meaningful cross-episode threats but never fabricate goals.
  if len(bucket)<4:
   for x in diverse(threats,n=5,gap=130):add(x,'development')
  # A nearby Full_time event can close the story if the clip contains it.
  for e in events:
   if e['typ']=='full_time' and not re.search(r'上半场|中场休息|半场结束',text(e['raw'].get('notes'))) and any(e['idx']==z['idx'] and e['t']>z['t'] for _,z in bucket):add(e,'ending')
  hero=None
  dated_goals=sorted([g for g in goals if g['team']],key=lambda g:(g['idx'],g['t']))
  if subtype=='落后追平':
   tally=collections.Counter()
   for g in dated_goals:
    prev1,prev2=tally['team_1'],tally['team_2']
    tally[g['team']]+=1
    if tally['team_1']==tally['team_2'] and ((g['team']=='team_1' and prev1<prev2) or (g['team']=='team_2' and prev2<prev1)):
     hero=g['team']
   if hero is None:issues.append('未通过进球顺序确认追平球队')
  elif subtype=='逆风翻盘':
   if dated_goals and len(set(g['team'] for g in dated_goals))>1:
    first=dated_goals[0]['team'];last=dated_goals[-1]['team'];
    hero=last if first!=last else None
  elif subtype=='领先守成':hero=dated_goals[0]['team'] if dated_goals else None
  elif subtype=='苦守保平':hero=None
  elif subtype=='比分拉锯':hero=None
  elif subtype=='点球大战决胜':hero=None
  elif subtype=='末段制胜':hero=dated_goals[-1]['team'] if dated_goals else None
  else:
   tally=collections.Counter(g['team'] for g in dated_goals)
   hero=tally.most_common(1)[0][0] if tally else None
  protag=teamname(hero)
  titleprefix=teamname(hero)+'的' if hero and teamname(hero) else ''
  headline=f'{titleprefix}{subtype}：{title_action(main)}' if main else f'{subtype}：比赛攻防与比分节点'
  if main and subtype in ('比分拉锯','大比分完胜','落后追平','逆风翻盘'):
   outcome='进球事件构成的比赛比分进展'
  if subtype=='点球大战决胜' and not any('penalty_shootout' in x['typ'] or '点球大战' in text(x['raw'].get('notes')) for x in events):
   issues.append('只有普通点球或比赛事件，尚无点球大战逐轮证据')
   headline=f'点球与关键射门回合：{title_action(main)}' if main else '点球相关比赛事件'
 elif cate=='攻防战术故事链':
  eligible=[e for e in threats if e['typ'] in ('shot','save','goal_line_clearance','goal')]
  team_counts=collections.Counter(e['team'] for e in eligible if e['team'])
  if subtype=='一方连续威胁':
   focus_team=team_counts.most_common(1)[0][0] if team_counts else None
   focus=[e for e in eligible if e['team']==focus_team] if focus_team else eligible
   protag=teamname(focus_team)
   hits=diverse(focus,n=6,gap=70)
   for x in hits:add(x,'core')
   main=hits[-1] if hits else None
   headline=f'{protag or "一方"}多轮进攻与门前险情：{title_action(main)}'
  elif subtype=='双方交替威胁':
   a=[e for e in eligible if e['team']=='team_1'];b=[e for e in eligible if e['team']=='team_2']
   for x in diverse(a,n=3,gap=90)+diverse(b,n=3,gap=90):add(x,'core')
   if len(a)==0 or len(b)==0:issues.append('双方进攻主体证据不足，不能直接认定交替威胁')
   main=max(eligible,key=lambda x:x['q']) if eligible else None
   headline=f'双方轮番制造机会：{title_action(main)}' if main else '双方攻守变化'
  else:
   a=[e for e in eligible if e['team']=='team_1'];b=[e for e in eligible if e['team']=='team_2']
   for x in diverse(a,n=3,gap=90)+diverse(b,n=3,gap=90):add(x,'core')
   if not a or not b:issues.append('缺少双方攻势变化证据')
   main=max(eligible,key=lambda x:x['q']) if eligible else None
   headline=f'攻守主导权变化与关键机会：{title_action(main)}' if main else '攻势变化'
  for x in list(bucket):
   if x[0]=='core' and x[1]['kind']=='event':attach(x[1],'tactical',100,100)
  # Relevant short chain as a coherent tactical episode if it doesn't duplicate a chosen action.
  rel=[c for c in chains if any(k in c['subtype'] for k in ('射门扑救','门线','反击','门柱','脱手'))]
  for c in diverse(rel,n=2,gap=140):add(c,'tactical_chain')
  outcome=None
 elif cate=='人物故事链':
  if '门将' in subtype:
   groups=collections.defaultdict(list)
   for x in saves:
    if x['keeper_team']:groups[x['keeper_team']].append(x)
   if groups:
    main_team=max(groups,key=lambda t:(len(groups[t]),sum(x['q'] for x in groups[t])));chosen=diverse(groups[main_team],n=6,gap=75)
    protag=teamname(main_team)+'门将' if teamname(main_team) else '同一防守方门将'
   else:
    chosen=diverse(saves,n=5,gap=85);protag=None;issues.append('扑救事件未明确门将所属球队，不能证明来自同一门将')
   for x in chosen:add(x,'core');attach(x,'keeper',130,100)
   # Consider a rare immediate goal after a save as aftermath, but do not assert causality.
   for g in goals:
    if any(g['idx']==v['idx'] and 0<g['t']-v['t']<240 for v in chosen):add(g,'aftermath')
   main=chosen[-1] if chosen else None
   if protag and chosen:
    attackers=collections.Counter(e['team'] for e in events if e['typ'] in ('shot','goal') and e['team'] and e['team']!=main_team)
    attacker=teamname(attackers.most_common(1)[0][0]) if attackers else '对方'
    headline=f'{protag}多次化解{attacker}攻势：{title_action(main)}'
   else:headline=f'{protag or "门将"}反复化险：{title_action(main)}' if main else '门前险情与防守表现'
   outcome=None
   if len(chosen)<2:issues.append('独立扑救回合少于2次，人物多次化险主线证据不足')
  else:
   goal_act=collections.defaultdict(list)
   for g in goals:
    if g['actor']:goal_act[g['actor']].append(g)
   scored_actor=next(iter(goal_act),None)
   pre=[];gg=[]
   if scored_actor:
    gg=goal_act[scored_actor]
    pre=[e for e in threats if e['actor']==scored_actor and e['typ'] not in ('goal','save') and any(e['idx']==g['idx'] and e['t']<g['t'] for g in gg)]
   if pre and gg:
    chosen=diverse(pre,n=3,gap=70)+gg[:2]
    protag=scored_actor
   else:
    chosen=diverse([e for e in threats if e['typ'] in ('shot','goal')],n=5,gap=110)
    issues.append('未证实威胁与得分动作来自同一球员')
   for x in chosen:add(x,'core');attach(x,'character',150,130)
   main=gg[-1] if gg else (chosen[-1] if chosen else None)
   headline=f'{protag or "球员"}从进攻参与到破门：{title_action(main)}' if main else '进攻球员的关键回合'
   outcome='标注球员最终破门' if pre and gg else None
 else:
  # Critical-turn stories are grounded in one decisive episode plus *real* surrounding events.
  chainpatterns={'判罚争议与战局转折':['进球无效','VAR','取消点球','改判'],
      '红牌冲击与攻守重构':['红牌'],
      '定位球战术执行与破局':['角球传中进球','快发定位球','点球命中'],
      '攻守转换与关键破门':['抢断/反击/失误后直接进球']}
  keychains=[c for c in chains if any(s.lower() in c['subtype'].lower() for s in chainpatterns.get(subtype,[]))]
  if subtype=='红牌冲击与攻守重构':
   rel=[e for e in events if e['typ']=='receive_a_card' and any('red' in v.lower() or '两黄' in v for v in attrs(e['raw'],'Card_Type'))]
  elif subtype=='判罚争议与战局转折':
   rel=[e for e in events if e['typ'] in ('video_assistant_referee','controversy','referees_decision')]
  elif subtype=='定位球战术执行与破局':
   rel=[e for e in events if issetpiece(e)];
  else:
   rel=[e for e in events if e['typ'] in ('defensive_action','shot') and ('counter_attack' in ' '.join(attrs(e['raw'],'Tactical_Play_Prior_Key_Action')).lower() or '抢断' in text(e['raw'].get('notes')) or '反击' in text(e['raw'].get('notes')))]
  anchors=diverse(keychains,n=2,gap=140) if keychains else diverse(rel,n=2,gap=125)
  for x in anchors:add(x,'core');attach(x,'setpiece' if '定位球' in subtype else 'counter' if '攻守转换' in subtype else 'judgement',250,210)
  # Find a truly annotated goal near a relevant short-chain segment, not random goals elsewhere.
  if subtype in ('定位球战术执行与破局','攻守转换与关键破门'):
   for c in anchors:
    nearby=[g for g in goals if g['idx']==c['idx'] and abs(g['t']-c['t'])<120]
    if nearby:
     gg=min(nearby,key=lambda g:abs(g['t']-c['t']));add(gg,'core')
     context_core(gg,events,bucket,mode='setpiece' if '定位球' in subtype else 'counter',span_pre=210,span_post=180)
   if not keychains:issues.append('未找到该类型非回放多事件短链，不能单凭普通角球/抢断断言形成破门')
  elif subtype=='红牌冲击与攻守重构' and not keychains and not rel:issues.append('缺少红牌动作或红牌判罚链')
  elif subtype=='判罚争议与战局转折' and not keychains:issues.append('未找到判罚改写短链，只能呈现判罚相关事件')
  if anchors:
   main=anchors[0]
   # The decisive source remains the anchor; later actions explain its consequences, not redefine it.
   main=anchors[0]
  if subtype=='判罚争议与战局转折':headline=f'争议判罚影响比赛：{title_action(main)}' if main else '判罚争议前后的攻防';outcome=None
  elif subtype=='红牌冲击与攻守重构':headline=f'红牌判罚与攻防变化：{title_action(main)}' if main else '红牌与攻防变化';outcome=None
  elif subtype=='定位球战术执行与破局':headline=f'定位球组织与门前机会：{title_action(main)}' if main else '定位球进攻回合';outcome=None
  else:headline=f'球权转换与射门机会：{title_action(main)}' if main else '攻守转换关键回合';outcome=None
  if anchors and anchors[0]['team']:protag=teamname(anchors[0]['team'])
 # Always select clean, distinct moments. Keep one evidence per almost-identical timespan.
 ranks={'core':100,'ending':80,'aftermath':73,'tactical_chain':68,'setup':65,'development':60,'score_context':40,'support':30}
 seq=sorted(bucket,key=lambda z:(z[1]['idx'],z[1]['t'],-ranks.get(z[0],50)))
 cleaned=[]
 for tag,x in seq:
  similar=[]
  for i,(oldtag,oldx) in enumerate(cleaned):
   if x['idx']!=oldx['idx']:continue
   overlap=max(0,min(x['end'],oldx['end'])-max(x['start'],oldx['start']))
   duration=min(x['end']-x['start'],oldx['end']-oldx['start'])
   if overlap>0 and duration>0 and overlap/duration>=0.75 and abs(x['t']-oldx['t'])<20:similar.append(i)
  if similar:
   i=similar[0];prevtag,prev=cleaned[i]
   xpriority=ranks.get(tag,50)+x['q']*0.06+(8 if x['kind']=='chain' else 0)
   ppriority=ranks.get(prevtag,50)+prev['q']*0.06+(8 if prev['kind']=='chain' else 0)
   if xpriority>ppriority:cleaned[i]=(tag,x)
  else:cleaned.append((tag,x))
 # Very long candidate chains should prioritize pivotal moments, not become event-by-event raw logs.
 if len(cleaned)>15:
  req=[i for i,(tag,x) in enumerate(cleaned) if tag=='core']
  support=[i for i in sorted(range(len(cleaned)),key=lambda i:cleaned[i][1]['q'],reverse=True) if i not in req]
  ids=set(req+support[:max(0,15-len(req))]);cleaned=[z for i,z in enumerate(cleaned) if i in ids]
 cleaned.sort(key=lambda z:(z[1]['idx'],z[1]['t']))
 # If a story has no selected events, retain empty public entry but register missing evidence only in QA.
 segments=[]
 for i,(tag,x) in enumerate(cleaned):
  previous=cleaned[i-1][1] if i else None
  following=cleaned[i+1][1] if i<len(cleaned)-1 else None
  if tag=='ending' or (x['typ']=='full_time' and not re.search(r'上半场|中场休息|半场结束',text(x['raw'].get('notes')))):role='resolution';func='交代比赛结束或故事后续'
  elif tag=='aftermath':role='resolution' if i>=len(cleaned)-2 else 'development';func='呈现关键回合之后的比赛回应'
  elif tag=='setup':role='setup';func='建立关键节点发生前的攻防背景'
  elif tag=='score_context':role='context';func='提供已标注的比分状态观察'
  elif tag=='tactical_chain':role='development';func='补充一段有完整动作关系的短程进攻或防守回合'
  elif tag=='core' and x['typ'] in ('goal','penalty_goal','header_goal') or tag=='core' and x['kind']=='chain' and ('进球' in x.get('subtype','') or '红牌' in x.get('subtype','')):
   role='turning_point' if any(z[0]=='core' for z in cleaned[i+1:]) else 'climax';func='呈现比赛关键结果或判罚节点'
  elif tag=='core':role='development' if i<len(cleaned)-1 else 'climax';func='呈现主线中的关键攻防动作'
  else:role='development';func='连接不同比赛回合并交代事件进展'
  rel=None
  if previous:
   dt=delta(x,previous)
   if x['kind']=='event' and previous['kind']=='event' and x['team'] and previous['team'] and x['team']!=previous['team'] and x['typ'] in ('shot','goal') and previous['typ'] in ('shot','goal'):
    rel='contrasting_attack'
   elif dt<45:rel='same_broadcast_sequence'
   else:rel='later_narrative_development'
  segment=record(x,role,func,rel,'core' if tag=='core' else 'supporting')
  segment['segment_id']=f'seg_{i+1:03d}';segment['order']=i+1
  segments.append(segment)
 if segments and not any(s['narrative_role']=='resolution' for s in segments):
  last=segments[-1]; last_x=cleaned[-1][1]
  if (last_x['typ']=='full_time' and not re.search(r'上半场|半场结束',text(last_x['raw'].get('notes')))) or cleaned[-1][0] in ('aftermath','ending'):last['narrative_role']='resolution'
 # Use actual match names, observed source actions and truthful story descriptors rather than template titles.
 matchup=match_name.split('_')[-1].strip() if '_' in match_name else match_name
 if len(matchup)>40:matchup=matchup[-40:]
 if headline and len(headline)>72:headline=headline[:69]+'…'
 def abridge(s):
  if '：' in s:s=s.split('：',1)[1]
  s=s.strip('。； ，')
  return (s[:64]+'…') if len(s)>66 else s
 core_indices=[i for i,s in enumerate(segments) if s['importance']=='core']
 key_idx=[]
 if segments:
  key_idx.append(0)
  if core_indices:key_idx.append(core_indices[0])
  if len(core_indices)>=2:key_idx.append(core_indices[-1])
  if len(segments)>=2:key_idx.append(len(segments)-1)
  key_idx=list(dict.fromkeys(key_idx))
 details=[abridge(segments[i]['description']) for i in key_idx]
 connective=['比赛中先出现','随后','此后','最后记录到']
 summary='；'.join(connective[i]+x for i,x in enumerate(details))+'。' if details else None
 st={'annotation_id':oldstory['annotation_id'], 'chain_category':cate,'story_chain_subtype':subtype,
     'story_title':headline or subtype}
 if protag:st['protagonist']=protag
 if summary:st['story_summary']=summary
 if outcome:st['story_outcome']=outcome
 st['segments']=segments
 return st,issues

allstories=[];audits=[];match_files=[];old_summ={x['annotation_id']:x for x in old};total_events=0;tot_chains=0
for i,match in enumerate(roster):
 streams,teams=populate(match)
 numev=sum(len(x['ev']) for x in streams);numch=sum(len(x['chs']) for x in streams)
 total_events+=numev;tot_chains+=numch
 stories=[]
 for os_ in by_match.get(match['id'],[]):
  st,issues=build_story(os_,streams,teams,match['name'])
  stories.append(st)
  allstories.append({'match_id':match['id'],'video_name':match['name'],**st})
  numsegs=len(st['segments']);oldnum=len(os_['segments']);countroles=collections.Counter(s['narrative_role'] for s in st['segments'])
  title=st['story_title']
  audits.append({'annotation_id':st['annotation_id'],'match_id':match['id'],'match_name':match['name'],'story_type':st['story_chain_subtype'],'story_title':title,
                 'old_segments':oldnum,'new_segments':numsegs,'change':numsegs-oldnum,
                 'core_segments':sum(s['importance']=='core' for s in st['segments']),
                 'context_segments':sum(s['importance']=='supporting' for s in st['segments']),
                 'has_resolution':int(countroles['resolution']>0),'source_event_count':sum(s['source_type']=='source_event' for s in st['segments']),
                 'source_chain_count':sum(s['source_type']=='source_chain' for s in st['segments']),
                 'source_event_inventory':numev,'source_chain_inventory':numch,
                 'attention':'；'.join(issues or ([] if numsegs>=3 else ['故事段数较少，可能仍不足以支撑长程叙事']))})
 if stories:
  out={'schema_version':'migu_story_chain_segments_v2','match_id':match['id'],'video_name':match['name'],'story_chains':stories}
  path=OUT/'matches'/f'{match["id"]}.json';path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');match_files.append(path)
assert len(allstories)==212
(OUT/'story_chains_212.json').write_text(json.dumps({'schema_version':'migu_story_chain_segments_v2','story_chains':allstories},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (OUT/'story_chains_212.jsonl').open('w',encoding='utf-8') as f:
 for x in allstories:f.write(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n')
with (OUT/'审核清单_212.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(audits[0]));w.writeheader();w.writerows(audits)
# Every used source must exist verbatim and times must be byte-for-byte traceable (within parse precision).
errors=[];seen_ids=[]
for st in allstories:
 for s in st['segments']:
  ident=(s['source_archive'],s['source_json_path']); source=cache.get(ident)
  if source is None:errors.append([st['annotation_id'],s['source_id'],'unknown file']);continue
  if s['source_type']=='source_event':
   obj=next((e for e in source.get('events',[]) if e.get('event_id')==s['source_id']),None)
   if obj is None or window(obj)!=(s['start_sec'],s['end_sec']) or not live(obj):errors.append([st['annotation_id'],s['source_id'],'invalid event'])
  else:
   obj=next((c for c in source.get('causal_chains',[]) if c.get('annotation_id')==s['source_id']),None)
   event_file=s['source_json_path'].replace('_causal.json','.json')
   event_source=cache.get((s['source_archive'],event_file))
   # Some files may use alternative archive/path; in that case validation must fail, not guess.
   if obj is None or obj.get('is_replay') is not False or len(obj.get('events',[]))<2 or event_source is None:
    errors.append([st['annotation_id'],s['source_id'],'invalid chain or event source'])
   else:
    m={e.get('bz_id'):e for e in event_source.get('events',[]) if e.get('bz_id')}
    linked=[m.get(v.get('bz_id')) for v in obj['events']]
    if not all(linked) or not all(live(e) for e in linked):errors.append([st['annotation_id'],s['source_id'],'unmatched or nonlive chain event'])
    else:
     w=(min(window(e)[0] for e in linked),max(window(e)[1] for e in linked))
     if w!=(s['start_sec'],s['end_sec']) or w[1]-w[0]>120:errors.append([st['annotation_id'],s['source_id'],'invalid linked source time'])
  assert s['end_sec']>s['start_sec']
 for seg in st['segments']:
  assert seg['narrative_role'] in ('context','setup','development','turning_point','climax','resolution')
  assert not any('待审核' in str(v) or 'DRAFT' in str(v) or 'UNVERIFIED' in str(v) for v in seg.values())
  assert seg['source_id']
 stats=collections.Counter()
 for x in audits:
  stats['stories']+=1;stats['old_segments']+=x['old_segments'];stats['new_segments']+=x['new_segments']
  stats['more_context']+=x['new_segments']>x['old_segments'];stats['has_resolution']+=bool(x['has_resolution']);stats['no_segments']+=x['new_segments']==0
  stats['lt3_segments']+=x['new_segments']<3;stats['event_nodes']+=x['source_event_count'];stats['chain_nodes']+=x['source_chain_count']
  stats['with_issues']+=bool(x['attention']);stats['changed_node_count']+=x['new_segments']!=x['old_segments']
manifest={'schema_version':'story_chain_context_rebuild_v2','source_matches':len(roster),'public_match_files':len(match_files),
   'source_live_events_available':total_events,'source_non_replay_multievent_chains_available':tot_chains,
   'statistics':dict(stats),'source_reference_errors':errors,'video_first_live_verified':0,
   'notes':['All 212 retain candidate identities; story narratives are grounded in first-party annotations and short chains',
    'Unreviewed source metadata does not prove first-live status',
    'Story subtype labels inherited from candidate roster do not prove existence of a realized story',
    'Relations same_broadcast_sequence, later_narrative_development, contrasting_attack are editorial/temporal, not assumed causality',
    'Review and disagreement details stored only in separate audit materials']}
(OUT/'validation_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'审核方法.md').write_text('''# 212条故事链：新版审核方法（不纳入公开JSON）

本次 v2 根据**完整比赛原子事件、短程因果链、事件时间、注释说明和部分角色线索**，重选叙事片段，禁止用故事类别模板机械填充；这是**源证据驱动的算法预标注**，不能宣称已人工完成视频金标。

## 审核步骤（逐条）
1. **真实故事**：先完整阅读该场同一视频对应的所有事件，判断故事是否真的存在；特别核对翻盘、点球大战、守成等比赛状态类候选与赛果；不成立的移出金标。
2. **主体一致**：门将故事必须证明同一门将/同一防守方，球员先威胁后得分必须绑定同一球员；战术链必须查攻方归属。
3. **视频片段**：使用 `source_archive + source_json_path + source_id` 找回原始记录；核对 `start_sec/end_sec` 对应视频本地时间轴；不能跨两个半场视频直接拼同一时间轴。
4. **首次直播**：`is_replay=false` 只是元数据，仍须看视频确认首次直播，无回放、无慢镜头混入。
5. **叙事连续性**：不要求固定五步，检查铺垫—关键行动—后续反应真实衔接，删除普通传球和重复片段；每个片段必须给故事增加信息。`relation_to_previous` 只是叙事/时间关系，不能解释为真实因果。
6. **比分与影响**：比分识别可能滞后、回跳甚至错误；普通事件里的比分不是进球证据；反击进球不能自动推出“士气提升/赢得比赛”，定位球类型不代表战术设计被证实。
7. **结果补齐**：需查终场结果、进球是否有效、VAR最终结果、球员归属。含空节点或只有1-2片段的候选重点判定是否成链；不要为凑212条虚构素材。

## 两个文件用途
- `审核清单_212.csv`：逐条列出新旧片段数、证据存量、薄弱项。
- `validation_manifest.json`：自动源引用与统计报告。

**重要**：该目录中的212是候选集合，并非212条人工确证长故事。正式金标统计须另有人工和视频审核结论。
''',encoding='utf-8')
import zipfile as zf
with zf.ZipFile(ROOT/'StoryChain_212_Context_Rebuild.zip','w',compression=zf.ZIP_DEFLATED) as z:
 for p in OUT.rglob('*'):
  if p.is_file():z.write(p,p.relative_to(OUT))
print(json.dumps({'out':str(OUT),'manifest':manifest},ensure_ascii=False,indent=2))