import json,csv,zipfile,re,collections,copy,pathlib,shutil,itertools
P=pathlib.Path('/mnt/data'); V=P/'StoryChain_212_Narrative_V4'; R=P/'StoryChain_V4_Review'; O=P/'StoryChain_212_Narrative_V5'; O.mkdir(exist_ok=True)
old=json.load(open(V/'story_chains_212.json')); data=copy.deepcopy(old); S=data['story_chains']; by={int(x['annotation_id'].split('-')[1]):x for x in S}; E={};C={};D={};B={}
for a in ['旧规足球.zip','足球第一批.zip','第二批足球.zip']:
 with zipfile.ZipFile(P/a) as z:
  for n in z.namelist():
   if not n.endswith('.json') or n.startswith('__MACOSX'):continue
   d=json.loads(z.read(n));D[a,n]=d
   if 'events' in d:
    E[a,n]={e['event_id']:e for e in d['events']}; B[a,n]=collections.defaultdict(list)
    for e in d['events']:B[a,n][e.get('bz_id')].append(e)
   if 'causal_chains' in d:C[a,n]={e['annotation_id']:e for e in d['causal_chains']}
def live(e):v=e.get('video_context',{});return v.get('broadcast_phase')=='LIVE' and v.get('is_replay') is False and not v.get('is_slow_motion') and not re.search('回放|慢动作|集锦|历史画面',str(e.get('notes','')))
def ep(n):return n.replace('_causal.json','.json')
def key(s):return s['source_archive'],s['source_json_path'],s['source_id']
def tm(e):m=e['media_time'];return m['start_time_sec'],m['end_time_sec']
def linked(s):
 a,n,i=key(s)
 if s['source_type']=='source_event':return [E[a,n][i]]
 c=C[a,n][i]; assert c['is_replay'] is False and len(c['events'])>=2
 out=[]
 for e in c['events']:
  m=B[a,ep(n)][e['bz_id']];assert len(m)==1;out+=m
 return out
def scope(s):return s['source_archive'],s['source_video_name']
def txt(a,n,e):
 t=str(e.get('notes') or e.get('event_type_zh') or '');
 for i,ch in [(1,'一'),(2,'二')]:
  name=D[a,n].get('teams',{}).get('team_'+str(i),{}).get('name','')
  if name:t=re.sub(r'(?<!\d)(?:'+str(i)+'|'+ch+')队',lambda m:name,t)
 return t
def mk(a,n,i,role,func,extra=()):
 i=f'event_{i:06d}' if isinstance(i,int) else i;e=E[a,n][i];assert live(e),(a,n,i);lo,hi=tm(e);assert hi>lo
 s=dict(segment_id='',order=0,narrative_role=role,narrative_function=func,description=txt(a,n,e),source_type='source_event',source_id=i,start_sec=lo,end_sec=hi,source_archive=a,source_json_path=n,source_video_name=D[a,n]['video']['file_name'],importance='core' if role in ('turning_point','climax') else 'supporting')
 sc=e.get('scores',{}).get('score_recognition');
 if re.fullmatch(r'\d+[:：]\d+',str(sc)):s['score_observed']=sc
 if extra:
  ids=[f'event_{j:06d}' for j in extra];assert all(live(E[a,n][j]) and tm(E[a,n][j])==tm(e) for j in ids),(i,ids);s['supporting_event_ids']=ids
  s['description']='；'.join(dict.fromkeys([txt(a,n,E[a,n][j]) for j in ids]+[s['description']]))
 return s
def file(a,suffix):
 l=[n for aa,n in E if aa==a and n.endswith(suffix)];assert len(l)==1,(a,suffix,l);return l[0]
A='旧规足球.zip'; F='足球第一批.zip'
def source(i):s=by[i]['segments'][0];return s['source_archive'],ep(s['source_json_path'])
def build(i,title,summary,outcome,protag,items,sub=None,cat=None,a=None,n=None):
 x=by[i]; a0,n0=source(i);a=a or a0;n=n or n0
 ss=[]
 for v in items:
  if isinstance(v,dict):ss.append(copy.deepcopy(v));continue
  j,r,f,*ex=v;ss.append(mk(a,n,j,r,f,ex[0] if ex else ()))
 x.update(story_title=title,story_summary=summary,story_outcome=outcome,segments=ss)
 if protag is None:x.pop('protagonist',None)
 else:x['protagonist']=protag
 if sub:x['story_chain_subtype']=sub
 if cat:x['chain_category']=cat
 return x
setup='setup';dev='development';turn='turning_point';cl='climax';res='resolution'
# evidence-specific rewrites; no outcome inferred from a subtype alone
build(16,'塞尔维亚落后后连入两球，后段再陷追分困局','瑞士先破门，塞尔维亚门将化险后，本队两次头球得分；后段比分记录转为2:3，塞尔维亚再次尝试攻门。','阶段性反超后再次落后','塞尔维亚',[(54,setup,'瑞士先得分，建立落后处境'),(57,dev,'门将化解瑞士继续扩大优势的机会'),(61,turn,'首个头球回应瑞士进球'),(65,cl,'第二个头球改变比分优势'),(93,res,'后段2:3比分下再次攻门，呈现反超后的失守')],sub='比分拉锯')
build(17,'瑞士先得分，塞尔维亚头球连追，比分优势再度易手','双方开场均制造机会，瑞士先得分；塞尔维亚两次头球入网，瑞士随后再次射门，后段比分记录2:3，体现优势的多次变化。','比分优势先后变化',None,[(11,setup,'瑞士先制造门前威胁'),copy.deepcopy(old['story_chains'][15]['segments'][1]),(54,turn,'瑞士打破僵局'),(61,turn,'塞尔维亚头球回应'),(65,turn,'塞尔维亚再次得分'),(69,dev,'瑞士在双方比分变化后继续攻门'),(93,cl,'后段2:3比分下塞尔维亚继续追分'),(108,res,'比赛结束')])
build(79,'阿联酋落后一球后反复攻门，头球追平再反超','阿曼13号先破门。阿联酋落后后多次射门遭化解，直至7号助攻16号头球追平；门将随后化险，18号再得分，后段比分保持领先至终场记录。','落后后扳平并反超','阿联酋',[(177,setup,'阿曼破门使阿联酋陷入落后'),(297,dev,'阿联酋首轮进攻被阿曼门将扑住'),(355,dev,'14号突破射门尝试追分'),(582,dev,'阿曼门将继续挡出阿联酋攻门'),(607,dev,'阿联酋再度遭遇扑救'),(712,turn,'7号助攻16号头球追平',(710,711)),(736,dev,'平局下阿联酋门将化险'),(774,cl,'18号接传球破门反超'),(809,dev,'阿曼落后后的射门打偏'),(879,res,'终场结束')])
build(80,'1:1僵局下阿联酋门将化险，18号破门后守住优势','追平后的比分为1:1。阿联酋门将先化解威胁，阿曼再次射门；双方争抢后18号得分，阿曼后续攻门打偏，比赛结束。','平局后取得领先并守住','阿联酋',[(736,setup,'1:1胶着时门将先化解威胁'),(748,dev,'阿曼再次试图打破平局'),(769,dev,'双方继续争夺球权'),(774,cl,'18号接传球得分，打破平局'),(796,dev,'阿曼落后后仍尝试射门'),(809,dev,'阿曼8号射门打偏'),(879,res,'终场结束')])
build(86,'塞尔塔落后时门将抱住射门，9号追平、18号反超','奥萨苏纳17号得分后比分变为2:1。塞尔塔门将顶住攻势，9号接角球扳平，球队继续射门寻找机会，18号破门，终场结束。','从落后到反超','塞尔塔维戈',[(528,setup,'奥萨苏纳进球建立落后背景'),(551,dev,'落后阶段门将控制对方射门'),(676,turn,'9号利用角球追平'),(689,dev,'7号继续试射但被挡'),(795,cl,'18号打破平局'),(834,res,'终场结束')])
build(87,'塞尔塔先得分，奥萨苏纳反超后再被连追','塞尔塔9号率先破门，随后奥萨苏纳攻势持续；比分记录进入1:1，17号再得分形成2:1。塞尔塔9号角球破门，18号最终打破2:2平局。','双方比分优势交替',None,[(344,setup,'塞尔塔率先得分'),(389,dev,'奥萨苏纳头球攻门遭扑救'),(425,dev,'奥萨苏纳继续头球试射'),(528,turn,'1:1观察状态下17号得分'),(676,turn,'塞尔塔9号角球得分回应'),(795,cl,'18号打破2:2平局'),(834,res,'终场结束')])
build(88,'2:2后塞尔塔攻门遭封堵，18号末段打破僵局','比分2:2时塞尔塔7号射门被阻挡，门将随后解围；18号禁区射门得分，奥萨苏纳后续调整阵容，终场结束。','2:2后取得领先','塞尔塔维戈',[(689,setup,'平局时射门遭阻挡'),(784,dev,'门将解围保持胶着状态'),(795,cl,'18号禁区破门'),(807,dev,'对方在2:3状态下换人调整'),(834,res,'终场结束')])
build(128,'德国两度击中门框后追平，7号再得分并扩大领先','下半场哥斯达黎加补射追平，德国两次击中门框后又失球；德国7号追平并再得分，9号随后扩大优势至2:4的比分观察。','德国末段取得并扩大领先','德国',[(318,setup,'哥斯达黎加补射追平'),(351,dev,'德国2号射门击柱'),(366,dev,'德国14号再次击柱'),(378,turn,'哥斯达黎加3号得分，德国面临落后'),(394,turn,'德国7号进球后记录2:2'),(419,dev,'平局时哥斯达黎加门将化险'),(444,dev,'德国14号再次尝试射门'),(449,cl,'德国7号再进球后记录2:3'),(472,res,'德国9号进球后记录2:4')])
build(129,'德国先经传中头球得分，哥斯达黎加任意球后取得领先','德国先组织角球，3号传中助攻10号头球得分；下半场哥斯达黎加12号发任意球后，3号射门得分，德国随后追平。','两队定位球机会与后续比分变化',None,[(13,setup,'德国早段角球组织'),(25,dev,'德国再次获得角球机会'),(36,turn,'德国3号传中助攻10号头球得分',(34,35)),(374,dev,'哥斯达黎加在1:1时开出任意球'),(378,cl,'随后哥斯达黎加3号得分，比分优势变化'),(394,res,'德国7号进球回应')])
build(132,'日本下半场连入两球，末段门将化解西班牙攻门','日本在0:1落后时先得分，西班牙门将同区间有扑救记录；日本随后再次破门，比分记录2:1。末段日本门将扑出西班牙10号射门。','日本由落后转为领先','日本',[(68,setup,'日本落后时西班牙犯规'),(75,turn,'日本首球扳平比分',(76,)),(81,cl,'日本再次破门'),(84,dev,'西班牙在2:1局面下换人'),(145,res,'日本门将化解西班牙10号攻门',(144,))])
build(133,'韩国先失球又遭越位取消，随后追平并在末段得分','葡萄牙先破门，韩国入网被判越位无效，随后再次得分；平局下韩国门将连续扑救，末段韩国助攻形成进球，比赛结束。','落后后扳平并再次破门','韩国',[(17,setup,'葡萄牙率先破门'),(62,dev,'韩国首次入网因越位无效，追分受阻'),(93,turn,'韩国再次得分，后续比分记录1:1'),copy.deepcopy(by[133]['segments'][6]),copy.deepcopy(by[133]['segments'][7]),(475,cl,'韩国传球助攻后破门，葡萄牙门将失误',(472,473,474)),(498,res,'终场结束')])
build(134,'1:1后韩国两次攻门被扑，末段助攻破门','比分1:1时韩国两次射门遭葡萄牙门将化解，随后末段传球助攻，门将失误后韩国打进一球，比赛结束。','平局后末段得分','韩国',[(427,setup,'韩国平局下首轮射门被扑',(426,)),(432,dev,'第二次射门仍被扑出',(431,)),(475,cl,'末段传球助攻后进球',(472,473,474)),(498,res,'终场结束')])
build(166,'亚美尼亚少打一人后门将屡次化险，爱尔兰两次破门','0:0时亚美尼亚球员吃红牌。其门将随后连续三次扑救，爱尔兰在0:0时得分，又在1:0时取得第二球，比赛结束。','红牌后长期防守并两次失球','亚美尼亚',[(128,turn,'红牌改变场上人数'),(134,dev,'红牌后第一次扑救'),(141,dev,'0:0时再次扑救'),(175,dev,'持续抵抗至后段'),(181,cl,'爱尔兰终于打破僵局'),(222,dev,'爱尔兰再次破门'),(235,res,'终场结束')])
# keep penalty story distinct; no VAR/controversy assertion
build(165,'0:0时亚美尼亚红牌，爱尔兰在人数变化后先得分','双方争顶后亚美尼亚球员被出示红牌；其门将随后扑救，爱尔兰在0:0状态下破门。','红牌后比分僵局被打破','爱尔兰',[(122,setup,'红牌前双方争夺'),(128,turn,'亚美尼亚球员被罚下'),(134,dev,'判罚后亚美尼亚门将化险'),(181,cl,'爱尔兰打破僵局')])
x=by[203];a=F;n=file(F,'2 2月15日 25-26赛季意甲第25轮 国际米兰VS尤文图斯 4K国语.json'); ss=[copy.deepcopy(s) for s in x['segments'][1:]]
ss+= [mk(a,n,j,r,f) for j,r,f in [(82,dev,'少打一人后的门将化险'),(114,turn,'国际米兰取得领先'),(138,turn,'尤文图斯回应扳平'),(178,cl,'国际米兰再次得分'),(214,res,'终场记录国际米兰获胜')]]
x.update(story_title='尤文两黄变一红后仍追平，国际米兰再度破门取胜',story_summary='1:1时尤文门线救险后球员两黄变一红。下半场门将继续扑救，国米94号先得分，尤文后腰追平，国米前腰再得分，终场记录国米胜利。',story_outcome='红牌后追平再失球',segments=ss)
# 15: actual sequence not sufficient to assert counterattack; use existing taxonomy for pressure story, preserve chain provenance
x=by[15];x.update(chain_category='攻防战术故事链',story_chain_subtype='一方连续威胁',story_title='巴西连续攻门遭瑞士化解，随后组织进攻破门',story_summary='0:0时瑞士门线救险并再次扑救；随后短链记录巴西任意球组织、关键传球与射门打进。',story_outcome='连续威胁后取得进球')
# split high-overlap Juventus story into late comeback focus, preserving broad score-duel story
x=by[153]; x['segments']=[s for s in x['segments'] if s['source_id'] in ['event_000093','event_000100','event_000113','event_000117','event_000121','event_000124']];x['story_summary']='比分2:3时尤文门将先扑救，19号随后头球扳平，32号继续射门，17号再次破门；国米在4:3时开出角球，终场结束。';x['story_outcome']='从2:3落后至4:3领先'
# distinguish attacking perspective versus keeper with evidence already selected, no artificial removal of shared evidence
x=by[94];x['segments']=[s for s in x['segments'] if s['source_id'] not in ['event_000018','event_000211','event_000035','event_000207']];x['story_title']='国际米兰由夺回球权到多次攻门，AC米兰门线化险';x['story_summary']='国际米兰夺回球权后射门打偏，30号任意球后射正，AC米兰门线救险；下半场国际米兰再次射正，AC米兰继续解围。';x['story_outcome']='多次威胁被对方防守化解'
x=by[96];n1=ep(x['segments'][0]['source_json_path']);a1=x['segments'][0]['source_archive'];q=next(s for s in x['segments'] if s['source_id']=='event_000035');a2,n2=key(q)[:2];x['segments']=[mk(a1,n1,209,setup,'AC米兰夺回球权形成攻势'),mk(a1,n1,211,dev,'国米门将挡出AC米兰11号射门',(210,)),mk(a2,n2,32,dev,'下半场AC米兰再次抢断组织进攻'),mk(a2,n2,37,turn,'门将先救险但AC米兰补射得分',(33,34,35,36)),mk(a2,n2,207,res,'0:1时国米门将继续化解射门',(206,))];x['story_title']='国米门将多次救险，AC米兰补射破门后仍继续化险';x['story_summary']='AC米兰夺回球权后11号射正，国际米兰门将救险。下半场AC米兰再次抢断并射正，门将挡出后对方补射入网；比分0:1后门将又阻断射门。';x['story_outcome']='多次救险但未能阻止补射破门，落后后继续扑救' 
# normalize and remove ordinary-resolution label only when rule flags it; no forced ending
review={r['故事ID']:r for r in csv.DictReader(open(R/'全量212条复审.csv',encoding='utf-8-sig'))}
for x in S:
 for idx,s in enumerate(x['segments']):
  if '收束节点仅普通动作' in review[x['annotation_id']]['问题筛查'] and s['narrative_role']=='resolution' and not any(e.get('event_type_zh') in ('比赛结束','进球','扑救','门线救险','射门','吃牌') or re.search('取消|改判|罚球|比分|终场',str(e.get('notes',''))) for e in linked(s)):
   s['narrative_role']='development';s['narrative_function']='交代该阶段的实际动作：'+s['description'];s['importance']='supporting'
  s['order']=idx+1;s['segment_id']=f'seg_{idx+1:03d}'
  if idx==0:s.pop('relation_to_previous',None)
  elif x!=old['story_chains'][int(x['annotation_id'].split('-')[1])-1]:s['relation_to_previous']='same_broadcast_sequence' if scope(s)==scope(x['segments'][idx-1]) and s['start_sec']<=x['segments'][idx-1]['end_sec']+2 else 'later_narrative_development'
# candidate pool only: actual segment evidence, distinct from gold set
cands=[]
for cid,a,n,ids,title,summary,p,mid in [
 ('OPEN-001',A,file(A,'03_1 11月10日 25-26赛季英超第11轮 曼城VS利物浦 4K国语__converted_1080p_H265_50fps.json'),[(47,setup,'点球被扑'),(124,cl,'同号球员后来头球破门')],'曼城9号失点后头球破门','9号点球被扑，随后接队友传中头球得分。','曼城9号',None),
 ('OPEN-002',F,file(F,'2 2月9日 25-26赛季英超第25轮 利物浦VS曼城 4K国语.json'),[(16,setup,'早段射门尝试'),(90,turn,'任意球直接破门'),(189,dev,'末段VAR介入'),(190,cl,'8号被出示红牌')],'利物浦8号从任意球破门到红牌离场','8号先尝试射门，任意球得分，末段VAR介入后有8号红牌记录。','利物浦8号','FH-AB34C7DC'),
 ('OPEN-003',A,file(A,'奥地利VS圣马力诺_国语.json'),[(58,setup,'早段头球得分'),(288,dev,'随后劲射高出横梁'),(702,turn,'后段进球备注帽子戏法'),(724,cl,'再进球备注大四喜')],'奥地利7号从早段破门到连续得分','7号早段头球破门、随后射高，后段进球备注分别记载帽子戏法和大四喜。','奥地利7号',None)]:
 ss=[mk(a,n,j,r,f) for j,r,f in ids]
 for k,s in enumerate(ss):s['segment_id']=f'seg_{k+1:03d}';s['order']=k+1
 if not mid:
  mid=next((x['match_id'] for x in S for s in x['segments'] if (s['source_archive'],ep(s['source_json_path']))==(a,n)),None)
 cands.append(dict(annotation_id=cid,match_id=mid,video_name=D[a,n]['video']['file_name'],chain_category='人物故事链',story_title=title,protagonist=p,story_summary=summary,segments=ss))
# validation of exact source and time, chronological within source, no duplicate spans in modified manual stories
errors=[];count=collections.Counter()
for x in S+cands:
 last={}
 for s in x['segments']:
  try:
   es=linked(s); assert es and all(live(e) for e in es);lo=min(tm(e)[0] for e in es);hi=max(tm(e)[1] for e in es);assert abs(lo-s['start_sec'])<.021 and abs(hi-s['end_sec'])<.021 and hi>lo;assert s['start_sec']>=last.get(scope(s),-1)-.021;last[scope(s)]=s['start_sec'];count[s['source_type']]+=1
  except Exception as e:errors.append((x['annotation_id'],s['source_id'],str(e)))
assert not errors,errors
# compare and output
changes=[];diff=[]
for x,y in zip(S,old['story_chains']):
 a={key(s):s for s in y['segments']};b={key(s):s for s in x['segments']};add=b.keys()-a.keys();drop=a.keys()-b.keys()
 if x!=y:
  changes.append(dict(故事ID=x['annotation_id'],比赛=x['video_name'],旧类型=y['story_chain_subtype'],新类型=x['story_chain_subtype'],旧标题=y['story_title'],新标题=x['story_title'],旧摘要=y['story_summary'],新摘要=x['story_summary'],旧片段数=len(y['segments']),新片段数=len(x['segments']),新增=len(add),删除=len(drop)))
  for act,ks,src in [('新增',add,b),('删除',drop,a)]:
   for k in sorted(ks):s=src[k];diff.append(dict(故事ID=x['annotation_id'],操作=act,归档=k[0],源文件=k[1],源ID=k[2],开始秒=s['start_sec'],结束秒=s['end_sec'],描述=s['description']))
def dump(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def write(p,rows):
 with open(p,'w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
dump(O/'story_chains_212.json',data);dump(O/'开放故事候选_3.json',{'story_chains':cands});(O/'story_chains_212.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False,separators=(',',':')) for x in S)+'\n',encoding='utf-8');write(O/'V5逐条修改记录.csv',changes);write(O/'V5片段增删明细.csv',diff)
shutil.copy(R/'新增人物故事线索.csv',O/'开放故事线索_20.csv');shutil.copy(R/'23条人工核验清单.csv',O/'23条人工核验清单_V4原始.csv')
# refresh previous 23, add new unresolved V5 items separately
human=list(csv.DictReader(open(R/'23条人工核验清单.csv',encoding='utf-8-sig')));lookup={x['annotation_id']:x for x in S}
for r in human:
 x=lookup[r['故事ID']];r['V5标题']=x['story_title'];r['V5现有片段入口']='\n'.join(f"{s['segment_id']} {s['source_archive']}::{s['source_json_path']}::{s['source_id']} [{s['start_sec']:.2f}–{s['end_sec']:.2f}s] {s['description']}" for s in x['segments'])
write(O/'23条人工核验清单.csv',human)
new={15:'ann_0025标签为反击，备注为任意球组织；已改连续威胁，核对真实进球及原类别。',16:'已改比分拉锯，核对2:3前缺失的瑞士进球和最终赛果；不要恢复逆风翻盘标签。',87:'0:1到1:1的奥萨苏纳进球缺失，核对完整比分。',128:'排除3729–4143秒及7878秒后可疑素材，重建德国末段主线；核对首次直播与有效进球。',129:'排除相同可疑区间；角球/任意球与进球是否同回合尚未证实。',131:'任意球与进球相隔约23秒，核对是否同一回合。',132:'主体改为日本；攻守转换是否发生须核对球权来源。',165:'红牌本身不证明判罚争议或改判；若无争议，调整类别或与166保持不同视角。',79:'头球追平前具体助攻/进球动作顺序需视频核对。',133:'核对越位无效、后续有效进球及比分。',203:'跨半场按文件顺序组织，核实红牌后攻防与赛果。'}
write(O/'V5新增人工核验事项.csv',[dict(故事ID=by[i]['annotation_id'],比赛=by[i]['video_name'],核验事项=t,入口='\n'.join(f'{s["source_archive"]}::{s["source_json_path"]}::{s["source_id"]} {s["start_sec"]:.2f}–{s["end_sec"]:.2f}' for s in by[i]['segments'])) for i,t in new.items()])
M=collections.defaultdict(list)
for x in S:M[x['match_id']].append(x)
(O/'matches').mkdir(exist_ok=True)
for mid,xs in M.items():dump(O/'matches'/f'{mid}.json',{'schema_version':data['schema_version'],'match_id':mid,'video_name':xs[0]['video_name'],'story_chains':xs})
exact=lambda rows:sum({key(s) for s in a['segments']}=={key(s) for s in b['segments']} for g in rows.values() for a,b in itertools.combinations(g,2))
orig=collections.defaultdict(list)
for x in old['story_chains']:orig[x['match_id']].append(x)
manifest=dict(stories=len(S),matches=len(M),segments=sum(len(x['segments']) for x in S),changed_stories=len(changes),source_changed_stories=sum(bool(r['新增'] or r['删除']) for r in changes),added=sum(r['新增'] for r in changes),removed=sum(r['删除'] for r in changes),source_events=sum(s['source_type']=='source_event' for x in S for s in x['segments']),source_chains=sum(s['source_type']=='source_chain' for x in S for s in x['segments']),old_exact_pairs=exact(orig),new_exact_pairs=exact(M),open_candidates=len(cands),reference_errors=errors,first_live_video_verified=0,prior_human_rows=len(human),new_review_rows=len(new))
dump(O/'validation_manifest.json',manifest);shutil.copy(__file__,O/'refine_story_v5.py');print(manifest)
