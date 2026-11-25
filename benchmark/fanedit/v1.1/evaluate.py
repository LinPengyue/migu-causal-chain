"""Diagnostic scoring on provisional references, not a final gold benchmark.
python evaluate.py --task causal --pred predictions.jsonl --data-dir .
python evaluate.py --task story --pred predictions.jsonl --exclude-known-dev
"""
import argparse, collections, json, math, pathlib

def read(path):
 with open(path,encoding='utf-8') as f:return [json.loads(l) for l in f if l.strip()]
def merge(xs):
 out=[]
 for a,b in sorted(xs):
  if out and a<=out[-1][1]:out[-1]=(out[-1][0],max(out[-1][1],b))
  else:out.append((a,b))
 return out
def intervals(x,task):
 d=collections.defaultdict(list)
 for t in ([x] if task=='causal' else x['segments']):d[t['video_id']].append((t['start_sec'],t['end_sec']))
 return {k:merge(v) for k,v in d.items()}
def tiou(a,b):
 i=sum(max(0,min(y,v)-max(x,u)) for k in a.keys()&b.keys() for x,y in a[k] for u,v in b[k]);n=sum(y-x for d in (a,b) for v in d.values() for x,y in v)-i
 return i/n if n else 0.
def sequence(x,task):
 # Story uses ordered evidence; remove repeated event IDs from the flattened sequence, retaining first occurrence.
 return tuple(x['event_ids']) if task=='causal' else tuple(dict.fromkeys(i for t in x['segments'] for i in t['event_ids']))
def label(x):return x['category'],x['subtype']
def match(edges):
 # Maximum cardinality bipartite matching, deterministic preference for higher IoU; not max-weight matching.
 used={}
 def add(i,seen):
  for j,_ in edges[i]:
   if j in seen:continue
   seen.add(j)
   if j not in used or add(used[j],seen):used[j]=i;return True
  return False
 for i in sorted(edges,key=lambda i:(len(edges[i]),i)):add(i,set())
 return [(i,j) for j,i in sorted(used.items())]
def div(x,y):return x/y if y else 0.
def f1(p,r):return div(2*p*r,p+r)
def evaluate(data,task,pred,threshold=.5,exclude_known_dev=False):
 d=pathlib.Path(data);videos={v['video_id']:v for v in read(d/'videos.jsonl')};events={e['event_id']:e for e in read(d/'atomic_events.jsonl')};matches={m['match_id']:m for m in read(d/'matches.jsonl')};ref=read(d/('causal_chains.jsonl' if task=='causal' else 'story_chains.jsonl'));vocab=json.loads((d/'taxonomy.json').read_text())[task];allowed={(a,b) for a,bs in vocab.items() for b in bs}
 valid_matches={m for m,x in matches.items() if not exclude_known_dev or x['development_exposure']!='known_development'}
 if task=='causal':eligible={r['video_id'] for r in ref}
 else:eligible=set(videos)
 validated=[];excluded_dev=0
 for j,x in enumerate(pred):
  m=x.get('match_id');assert m in matches, f'Unknown match at prediction {j}: {m}'
  if m not in valid_matches:excluded_dev+=1;continue
  assert label(x) in allowed, f'Invalid taxonomy at prediction {j}: {label(x)}'
  assert task=='causal' or x.get('segments'),f'Empty segments: {j}'
  for t in ([x] if task=='causal' else x['segments']):
   v=t['video_id'];assert v in eligible and videos[v]['match_id']==m,f'Invalid or non-scoring source at prediction {j}: {v}'
   lo,hi=t['start_sec'],t['end_sec'];assert all(isinstance(q,(int,float)) and math.isfinite(q) for q in [lo,hi]) and 0<=lo<hi<=videos[v]['duration_sec'],f'Invalid interval: {j}'
   assert t.get('event_ids'),f'Empty event_ids at prediction {j}'
   assert all(i in events and events[i]['video_id']==v for i in t['event_ids']),f'Invalid event reference: {j}'
  validated.append(x)
 pred=validated;ref=[x for x in ref if x['match_id'] in valid_matches];gp=collections.defaultdict(list);gr=collections.defaultdict(list)
 for x in pred:gp[x['match_id']].append(x)
 for x in ref:gr[x['match_id']].append(x)
 loc=typed=exact=0;ious=[];efs=[];type_ok=0;per=collections.defaultdict(lambda:[0,0,0])
 for x in pred:per[label(x)][0]+=1
 for x in ref:per[label(x)][1]+=1
 for m in sorted(valid_matches):
  ps,rs=gp[m],gr[m];pi=[intervals(x,task) for x in ps];ri=[intervals(x,task) for x in rs];pe=[sequence(x,task) for x in ps];re=[sequence(x,task) for x in rs];le={};te={};ee={}
  for i,p in enumerate(ps):
   opts=sorted(((j,tiou(pi[i],r)) for j,r in enumerate(ri)),key=lambda x:(-x[1],x[0]));le[i]=[(j,s) for j,s in opts if s>=threshold];te[i]=[(j,s) for j,s in le[i] if label(p)==label(rs[j])];ee[i]=[(j,s) for j,s in te[i] if pe[i]==re[j]]
  lm=match(le);tm=match(te);em=match(ee);loc+=len(lm);typed+=len(tm);exact+=len(em)
  for i,j in lm:type_ok+=label(ps[i])==label(rs[j])
  for i,j in tm:
   ious.append(tiou(pi[i],ri[j]));a,b=set(pe[i]),set(re[j]);efs.append(f1(div(len(a&b),len(a)),div(len(a&b),len(b))));per[label(ps[i])][2]+=1
 pr,rc=div(typed,len(pred)),div(typed,len(ref));by=[]
 for (cat,sub),(p,r,tp) in sorted(per.items()):
  pp,rr=div(tp,p),div(tp,r);by.append({'category':cat,'subtype':sub,'pred':p,'ref':r,'tp':tp,'precision':pp,'recall':rr,'f1':f1(pp,rr)})
 return {'status':'PROVISIONAL_DIAGNOSTIC_NOT_GOLD','task':task,'matches':len(valid_matches),'predictions':len(pred),'references':len(ref),'ignored_known_development_predictions':excluded_dev,'tiou_threshold':threshold,'location_matched':loc,'type_correct_location_matches':type_ok,'type_accuracy_on_location_matches':div(type_ok,loc),'typed_matches':typed,'precision':pr,'recall':rc,'f1':f1(pr,rc),'macro_f1_observed_or_predicted_types':div(sum(x['f1'] for x in by),len(by)),'exact_ordered_event_match_recall':div(exact,len(ref)),'exact_ordered_event_matches':exact,'mean_tiou_on_typed_matches':div(sum(ious),len(ious)),'mean_event_set_f1_on_typed_matches':div(sum(efs),len(efs)),'by_type':by,'caveat':'References are provisional and non-exhaustive; apparent false positives may be valid unannotated chains. Human narrative and first-live assessment are not computed.'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data-dir',default=str(pathlib.Path(__file__).parent));p.add_argument('--task',required=True,choices=['causal','story']);p.add_argument('--pred',required=True);p.add_argument('--tiou',type=float,default=.5);p.add_argument('--exclude-known-dev',action='store_true');p.add_argument('--out');a=p.parse_args();assert 0<a.tiou<=1
 x=evaluate(a.data_dir,a.task,read(a.pred),a.tiou,a.exclude_known_dev);s=json.dumps(x,ensure_ascii=False,indent=2);print(s)
 if a.out:pathlib.Path(a.out).write_text(s+'\n',encoding='utf-8')
