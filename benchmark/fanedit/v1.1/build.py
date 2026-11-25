"""Rebuild provisional FanEdit paired benchmark from the four original archives.
Usage: python build.py --input-dir /path/to/archives --output-dir /path/to/output
"""
import argparse, collections as co, csv, hashlib, json, math, pathlib, re, zipfile
p=argparse.ArgumentParser();p.add_argument('--input-dir',type=pathlib.Path,default=pathlib.Path('/mnt/data'));p.add_argument('--output-dir',type=pathlib.Path,default=pathlib.Path(__file__).parent);args=p.parse_args();OUT=args.output_dir;OUT.mkdir(parents=True,exist_ok=True)
def locate(stem):
 for name in [stem+'.zip',stem+'(1).zip']:
  path=args.input_dir/name
  if path.is_file():return path
 raise FileNotFoundError(stem)
def dump(name,x):
 with (OUT/name).open('w',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2);f.write('\n')
def jsonl(name,rows):
 with (OUT/name).open('w',encoding='utf-8') as f:
  for x in rows:f.write(json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n')
def writecsv(name,rows,keys):
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
paths={n+'.zip':locate(n) for n in ['旧规足球','足球第一批','第二批足球','StoryChain_212_Narrative_V5']}
z=zipfile.ZipFile(paths['StoryChain_212_Narrative_V5.zip']);S=json.loads(z.read('story_chains_212.json'))['story_chains'];audit=co.defaultdict(list)
for n in ['23条人工核验清单.csv','V5新增人工核验事项.csv']:
 for r in csv.DictReader(z.read(n).decode('utf-8-sig').splitlines()):audit[r['故事ID']].append({'file':n,'reason':r.get('人工需确认事项') or r.get('核验事项'),'review_status':'unresolved'})
D={};C={}
for a,path in paths.items():
 if a.startswith('Story'):continue
 with zipfile.ZipFile(path) as zz:
  for n in zz.namelist():
   if not n.endswith('.json') or n.startswith('__MACOSX'):continue
   x=json.loads(zz.read(n));
   if 'causal_chains' in x:C[a,n]=x
   elif 'events' in x:D[a,n]=x
M=co.defaultdict(set);titles={}
for s in S:
 m=s['match_id'];titles[m]=s['video_name']
 for t in s['segments']:M[m].add((t['source_archive'],t['source_json_path'].replace('_causal.json','.json')))
# Supplement the three same-match, non-overlapping half sources not cited by V5 story segments.
EXTRA_SOURCES={
 'FH-C5F1A809': ('足球第一批.zip','1 10月26日 25-26赛季英超第9轮 曼联VS布莱顿 4K国语.json'),
 'FH-62898B12': ('足球第一批.zip','1 4月19日 25-26赛季英超第33轮 切尔西VS曼联 4K国语.json'),
 'FH-4333C76C': ('足球第一批.zip','2 11月30日 25-26赛季英超第13轮 水晶宫VS曼联 4K国语.json'),
}
for m,k in EXTRA_SOURCES.items():
 assert m in M and k in D and (k[0],k[1].replace('.json','_causal.json')) in C
 M[m].add(k)
B={k:co.defaultdict(list) for k in D}; E={k:{} for k in D}
for k,d in D.items():
 for e in d['events']:
  if e.get('bz_id'):B[k][e['bz_id']].append(e)
  assert e['event_id'] not in E[k],(k,e['event_id']);E[k][e['event_id']]=e
H=co.defaultdict(list)
for s in S:
 if s['annotation_id'] in audit:
  for t in s['segments']:
   if t['source_type']=='source_chain':H[t['source_archive'],t['source_json_path'],t['source_id']].append(s['annotation_id'])
# IDs scoped by exact source archive and JSON path, never by bare event ID.
def srcid(m,k):return m+'-V'+hashlib.sha256(('::'.join(k)).encode()).hexdigest()[:12]
def eid(m,k,e):return srcid(m,k)+':E:'+e['event_id']
def cid(m,k,c):return srcid(m,k)+':C:'+c['annotation_id']
def mt(e):return e.get('media_time',{})
def num(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def suspect(m,k,lo,hi):
 if m=='FH-AD42F871' and ('哥斯达黎加vs德国' in k[1]):return (lo<4143 and hi>3729) or hi>7878
 if m=='FH-DF83CD36' and ('威尔士vs伊朗' in k[1]):return hi>=6237.1
 return False
def event_reasons(m,k,e):
 v=e.get('video_context',{});t=mt(e);lo,et,hi=[t.get(f) for f in ['start_time_sec','event_time_sec','end_time_sec']];dur=D[k]['video']['duration_sec'];r=[]
 if v.get('broadcast_phase')!='LIVE' or v.get('is_replay') is not False or v.get('is_slow_motion') or re.search('回放|慢动作|集锦|历史画面',str(e.get('notes',''))):r.append('not_live_by_metadata')
 if not(all(num(x) for x in (lo,et,hi)) and 0<=lo<=et<=hi<=dur and lo<hi):r.append('invalid_media_interval')
 elif suspect(m,k,lo,hi):r.append('known_audit_time_interval')
 return r
# Actual official labels preserved; do not infer category from a model or rewrite other labels.
CAUSAL_VOCAB={'结果链':['角球传中进球链','射门被扑后补射进球链','抢断/反击/失误后直接进球链','点球命中链','红牌判罚链','其他'],'修正链':['进球无效链','VAR取消点球链','VAR改判链'],'险情链':['射门扑救链','射中门柱/横梁链','门框后二次进攻链','门线极限救险链'],'特殊链':['手抛球发动进攻链','乌龙球致因链','门将脱手致险链','折射/变线入网链','快发定位球链']}
# AB34C7DC has two annotations of the first half. Retain the older denser file for causal scoring;
# the alternate first-half video remains addressable only for existing story evidence.
ALT={k for k in M['FH-AB34C7DC'] if k[0]=='足球第一批.zip' and k[1].startswith('1 2月9日 ')}
chain_rows=co.defaultdict(list);excluded=[];chain_lookup={}; source_owner={};
for m,ks in sorted(M.items()):
 for k in sorted(ks):
  assert k in D and k not in source_owner,(m,k);source_owner[k]=m
  ck=(k[0],k[1].replace('.json','_causal.json'));seen=set()
  for c in C.get(ck,{}).get('causal_chains',[]):
   rid=c['annotation_id'];rs=[];es=c.get('events',[]);le=[]
   if c.get('is_replay') is not False:rs.append('replay_or_unknown')
   if len(es)<2:rs.append('fewer_than_two_nodes')
   if c.get('causal_chain_subtype') not in CAUSAL_VOCAB.get(c.get('chain_category'),[]):rs.append('unrecognized_category_pair')
   if k in ALT:rs.append('alternate_duplicate_half_not_for_causal_scoring')
   if (ck[0],ck[1],rid) in H:rs.append('unresolved_story_audit_chain_reference')
   for en in es:
    q=B[k].get(en.get('bz_id'),[])
    if len(q)!=1:rs.append('unresolved_or_ambiguous_bz_id');break
    le.append(q[0])
   if len(le)==len(es) and le:
    for e in le:rs+=event_reasons(m,k,e)
    ids=[eid(m,k,e) for e in le]; ts=[mt(e).get('event_time_sec') for e in le]
    # Timing and exact dedup defined on linked atomic media timeline, not t_ms from causal file.
    if len(set(ids))<2 or len(set(ts))<2:rs.append('not_distinct_atomic_nodes_or_times')
    if all(num(t) for t in ts):
     if any(x>y for x,y in zip(ts,ts[1:])):rs.append('nonmonotonic_linked_event_time')
     if max(ts)-min(ts)>120:rs.append('span_over_120s')
    else:rs.append('invalid_event_time')
    if all(num(mt(e).get('start_time_sec')) and num(mt(e).get('end_time_sec')) for e in le):
     lo=min(mt(e)['start_time_sec'] for e in le);hi=max(mt(e)['end_time_sec'] for e in le)
     if hi-lo>120:rs.append('window_over_120s')
    else:lo=hi=None
    key=(c.get('chain_category'),c.get('causal_chain_subtype'),tuple(ids))
    if key in seen:rs.append('duplicate_chain')
   else:lo=hi=None;ids=[];key=None
   row={'chain_id':cid(m,k,c),'match_id':m,'video_id':srcid(m,k),'category':c.get('chain_category'),'subtype':c.get('causal_chain_subtype'),'other_name':c.get('causal_chain_other_name'),'event_ids':ids,'start_sec':lo,'end_sec':hi,'nodes':[{'event_id':eid(m,k,e),'order':i+1,'source_chain_event_id':en.get('event_id'),'source_chain_type':en.get('type_en'),'source_chain_t_ms':en.get('t_ms')} for i,(en,e) in enumerate(zip(es,le))],'source':{'archive':ck[0],'path':ck[1],'annotation_id':rid,'bz_id':c.get('bz_id'),'segment_time_sketch':c.get('segment_time_sketch'),'segment_time_video':c.get('segment_time_video')},'label_status':'provisional_source_annotation','first_live_verified':False,'is_benchmark_gold':False}
   rs=list(dict.fromkeys(rs));chain_lookup[ck[0],ck[1],rid]=(row,rs)
   if rs:excluded.append({'match_id':m,'chain_id':row['chain_id'],'source':row['source'],'reasons':rs,'audit_story_ids':H.get((ck[0],ck[1],rid),[])})
   else:seen.add(key);chain_rows[m].append(row)
A=[s for s in S if s['annotation_id'] not in audit];selected=sorted({s['match_id'] for s in A if chain_rows[s['match_id']]});print('selected',len(selected),'chains',sum(len(chain_rows[m]) for m in selected),'stories',sum(s['match_id'] in selected for s in A));
# Use match-level grouping; never offset half-local media times. Separate rejected story rows from reference data.
selected=set(selected);stories=[];story_holds=[];story_evidence=[];story_refs=set();story_issues=[]
for s in S:
 m=s['match_id'];sid=s['annotation_id']
 if sid in audit or m not in selected:
  story_holds.append({'story_id':sid,'match_id':m,'reasons':audit.get(sid,[]) or [{'reason':'no_eligible_paired_causal_chains'}],'original':s});continue
 r={k:v for k,v in s.items() if k not in ('segments','annotation_id','chain_category','story_chain_subtype')};r.update(story_id=sid,category=s['chain_category'],subtype=s['story_chain_subtype'],label_status='provisional_source_grounded_story',first_live_verified=False,is_benchmark_gold=False,segments=[])
 for t in s['segments']:
  k=(t['source_archive'],t['source_json_path'].replace('_causal.json','.json'));v=srcid(m,k);refs=[];cc=None;issue=[]
  if t['source_type']=='source_event':
   e=E[k][t['source_id']];refs=[eid(m,k,e)];issue+=event_reasons(m,k,e)
  else:
   cr,rs=chain_lookup[t['source_archive'],t['source_json_path'],t['source_id']];refs=cr['event_ids'];cc=cr['chain_id'];
   # A chain may be ineligible for the short task (e.g. alternate version or length) but still usable as an ordered evidence segment.
   fatal=set(rs)-{'alternate_duplicate_half_not_for_causal_scoring','duplicate_chain','window_over_120s','span_over_120s'}
   if fatal:issue+=['source_chain:'+x for x in sorted(fatal)]
   if rs:story_evidence.append({'story_id':sid,'segment_id':t['segment_id'],'chain':cr,'short_task_exclusion_reasons':rs})
  for i in t.get('supporting_event_ids',[]):
   e=E[k][i];refs.append(eid(m,k,e));issue+=event_reasons(m,k,e)
  if suspect(m,k,t['start_sec'],t['end_sec']):issue.append('known_audit_time_interval')
  if not (0<=t['start_sec']<t['end_sec']<=D[k]['video']['duration_sec']):issue.append('invalid_story_interval')
  if not refs:issue.append('no_atomic_refs')
  q=dict(t);q.update(video_id=v,event_ids=list(dict.fromkeys(refs)),causal_chain_id=cc,source_chain_eligible_for_short_task=(not rs if cc else None),source_time_axis='source_video_media_seconds');r['segments'].append(q);story_refs.update(refs)
  if issue:story_issues.append({'story_id':sid,'match_id':m,'segment_id':t['segment_id'],'issues':issue})
 stories.append(r)
# If known-invalid evidence is present, do NOT quietly keep that story as a scoring reference.
bad_extra={q['story_id'] for q in story_issues}
if bad_extra:
 for s in S:
  if s['annotation_id'] in bad_extra:story_holds.append({'story_id':s['annotation_id'],'match_id':s['match_id'],'reasons':[q for q in story_issues if q['story_id']==s['annotation_id']],'original':s})
 stories=[s for s in stories if s['story_id'] not in bad_extra]
# Keep the recovered paired inventory; record any match that loses all usable stories rather than pretending it still has both tasks.
paired=selected & {s['match_id'] for s in stories};selected=paired;stories=[s for s in stories if s['match_id'] in selected];chains=[c for m in sorted(selected) for c in chain_rows[m]]
# Export model inputs independently, include source-scoped original event metadata for reproducibility.
video_rows=[];events=[];input_rows=[];held_events=[]
for m in sorted(selected):
 for k in sorted(M[m]):
  v=srcid(m,k);d=D[k];ev=[];video_rows.append({'match_id':m,'video_id':v,'video_name':d['video']['file_name'],'duration_sec':d['video']['duration_sec'],'teams':d.get('teams'),'source_archive':k[0],'source_event_path':k[1],'source_match_id':d.get('match_id'),'annotation_scope':d.get('annotation_scope'),'causal_eval_source':k not in ALT,'timeline':'source_video_media_seconds'})
  for e in d['events']:
   rs=event_reasons(m,k,e);rid=eid(m,k,e)
   if rs:held_events.append({'event_id':rid,'match_id':m,'video_id':v,'source_event_id':e['event_id'],'reasons':rs});continue
   a={'event_id':rid,'match_id':m,'video_id':v,'type':e.get('event_type'),'type_zh':e.get('event_type_zh'),'start_sec':mt(e)['start_time_sec'],'end_sec':mt(e)['end_time_sec'],'event_time_sec':mt(e)['event_time_sec'],'attributes':e.get('attributes'),'scores':e.get('scores'),'description':e.get('notes'),'broadcast_context':e.get('video_context'),'source_event_id':e['event_id'],'source_bz_id':e.get('bz_id'),'is_model_target':e.get('is_model_target'),'annotation_quality':e.get('annotation_quality')};events.append(a);ev.append(a)
  input_rows.append({'match_id':m,'video_id':v,'video_name':d['video']['file_name'],'duration_sec':d['video']['duration_sec'],'teams':d.get('teams'),'causal_eval_source':k not in ALT,'events':[{k:e[k] for k in ('event_id','type','type_zh','event_time_sec','start_sec','end_sec','attributes','scores','description')} for e in sorted(ev,key=lambda q:(q['event_time_sec'],q['event_id']))]})
# Explicit source-based task records. No ground truth in event-only input. Do not use story reference titles as prompts.
match_rows=[];narrative_vocab=co.defaultdict(set)
for s in S:narrative_vocab[s['chain_category']].add(s['story_chain_subtype'])
for m in sorted(selected):
 cc=[c for c in chains if c['match_id']==m];ss=[s for s in stories if s['match_id']==m];vv=[v for v in video_rows if v['match_id']==m];match_rows.append({'match_id':m,'match_name':titles[m],'video_ids':[v['video_id'] for v in vv],'causal_eval_video_ids':[v['video_id'] for v in vv if v['causal_eval_source']],'causal_chain_count':len(cc),'story_chain_count':len(ss),'development_exposure':'known_development' if m in {'FH-E57877ED','FH-723B1912','FH-5DA0F989','FH-34B9C8A4'} else 'unverified','evaluation_split':'not_assigned'})
jsonl('matches.jsonl',match_rows);jsonl('videos.jsonl',video_rows);jsonl('atomic_events.jsonl',events);jsonl('event_inputs.jsonl',input_rows);jsonl('causal_chains.jsonl',chains);jsonl('story_chains.jsonl',stories);jsonl('quarantine_causal.jsonl',excluded);jsonl('quarantine_story.jsonl',story_holds);jsonl('quarantine_events.jsonl',held_events);jsonl('story_evidence_only_chains.jsonl',[x for x in story_evidence if x['story_id'] not in bad_extra and x['chain']['match_id'] in selected]);
dump('taxonomy.json',{'causal':CAUSAL_VOCAB,'story':{k:sorted(v) for k,v in narrative_vocab.items()},'causal_label_policy':'preserve original Chinese category/subtype; other_name is auxiliary, not a new class'});
# Validate every reference and interval against actual export, plus cross-task isolation.
idx={e['event_id']:e for e in events};vidx={v['video_id']:v for v in video_rows};cidx={c['chain_id']:c for c in chains}; errors=[]
for c in chains:
 if any(i not in idx or idx[i]['video_id']!=c['video_id'] for i in c['event_ids']):errors.append(('chain_ref',c['chain_id']))
 if not 0<=c['start_sec']<c['end_sec']<=vidx[c['video_id']]['duration_sec']:errors.append(('chain_interval',c['chain_id']))
for s in stories:
 for t in s['segments']:
  if any(i not in idx or idx[i]['video_id']!=t['video_id'] for i in t['event_ids']):errors.append(('story_ref',s['story_id'],t['segment_id']))
  if t['source_chain_eligible_for_short_task'] and t['causal_chain_id'] not in cidx:errors.append(('story_chain_ref',s['story_id'],t['segment_id']))
  if not 0<=t['start_sec']<t['end_sec']<=vidx[t['video_id']]['duration_sec']:errors.append(('story_interval',s['story_id'],t['segment_id']))
assert len(idx)==len(events) and len(cidx)==len(chains) and len({s['story_id'] for s in stories})==len(stories)
assert not errors,errors
ca=co.Counter(c['category'] for c in chains);cs=co.Counter(c['subtype'] for c in chains);sa=co.Counter(s['category'] for s in stories);st=co.Counter(s['subtype'] for s in stories)
summary={'status':'PROVISIONAL_EVAL_REFERENCE_NOT_GOLD','source_archives_sha256':{k:sha(v) for k,v in paths.items()},'matches':len(selected),'video_sources':len(video_rows),'causal_eval_video_sources':sum(v['causal_eval_source'] for v in video_rows),'atomic_events':len(events),'causal_chains':len(chains),'story_chains':len(stories),'story_segments':sum(len(s['segments']) for s in stories),'causal_category_counts':ca,'causal_subtype_counts':cs,'story_category_counts':sa,'story_subtype_counts':st,'causal_defined_subtypes':sum(map(len,CAUSAL_VOCAB.values())),'story_defined_subtypes':sum(map(len,narrative_vocab.values())),'initial_story_count':len(S),'original_audit_story_holds':len(audit),'additional_story_holds':len(bad_extra),'known_development_matches':[m['match_id'] for m in match_rows if m['development_exposure']=='known_development'],'quarantine_causal_rows_all_94_sources':len(excluded),'quarantine_causal_reason_counts':co.Counter(r for e in excluded for r in e['reasons']),'reference_errors':errors,'first_live_video_verified':0,'notes':['No complete historical per-chain audit exclusion manifest was available. Known V5 audit issues are quarantined; remaining records are provisional.','Previous v1 counted only V5-cited sources (737); three non-overlapping half sources add 13 eligible chains, yielding 750. The older 769 has no row-level manifest.','Not all source videos are full matches; no invented full-match offset.','Unannotated/missing positives cannot establish exhaustiveness.']};dump('manifest.json',summary);dump('validation.json',{'reference_errors':errors,'unique_event_ids':len(idx),'unique_chain_ids':len(cidx),'all_matches_have_both_tasks':all(m['causal_chain_count'] and m['story_chain_count'] for m in match_rows),'extra_story_issues':story_issues,'time_unit':'seconds','video_verified':False});writecsv('match_inventory.csv',[{k:m[k] for k in ('match_id','match_name','causal_chain_count','story_chain_count','development_exposure','evaluation_split')} for m in match_rows],['match_id','match_name','causal_chain_count','story_chain_count','development_exposure','evaluation_split']);print(json.dumps(summary,ensure_ascii=False,indent=2))
