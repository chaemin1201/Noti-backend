#!/usr/bin/env python3
"""run_real_e2e.py 가 저장한 결과(JSON)를 한 장짜리 HTML 보고서로 만든다. 서버 없이 브라우저에서 바로 열린다 (외부 파일·인터넷 불필요).

사용법
  python run_real_e2e.py --upload 파일1 파일2 --rows 0 --out 결과.json
  python make_report.py 결과.json [보고서.html]

보고서: 상태별 개수, 유형별 개수, 문제마다 (유형·상태·해야 할 일·이유) 표, 문제를 누르면 저장될 내용(설명, 보기·정답, 테스트 케이스, 코드)과 AI 가 표시한 확인필요.
JSON 에 'before'(승인 전 상태)가 있으면 그것을 쓴다. 없으면 전체 승인 뒤 상태라 모두 등록됨으로 보인다.
"""
import json, os, sys

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>문제 등록 결과</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1d2330;--mut:#667085;--line:#e3e6ec;--ok:#1a7f4b;--okb:#dff3e8;--rv:#a15c00;--rvb:#fdeccf;--in:#1c5fb8;--inb:#dbe8fb;--hd:#b42318;--hdb:#fbdcd8;--gr:#5b6472;--grb:#e8eaee;--code:#f1f3f6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#12151b;--card:#1b1f27;--tx:#e8ebf1;--mut:#9aa3b2;--line:#2b313c;--ok:#59d08f;--okb:#17372a;--rv:#f3b65b;--rvb:#42310f;--in:#7db2f5;--inb:#162f52;--hd:#f59a90;--hdb:#4a1d19;--gr:#aab2bf;--grb:#2a303a;--code:#242a34}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.55 system-ui,"Malgun Gothic",sans-serif}
.w{max-width:1100px;margin:0 auto;padding:24px 16px 60px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.card b{display:block;font-size:26px;line-height:1.1}.card span{color:var(--mut);font-size:13px}
.bar{display:flex;height:16px;border-radius:8px;overflow:hidden;background:var(--grb);margin:6px 0 4px}.bar i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--mut);margin-bottom:18px}.legend em{font-style:normal;display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 12px}.filters button{border:1px solid var(--line);background:var(--card);color:var(--tx);border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer}.filters button[aria-pressed=true]{background:var(--tx);color:var(--bg);border-color:var(--tx)}
.row{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:8px}.row>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:minmax(90px,1.1fr) 70px 120px minmax(120px,2.4fr);gap:10px;align-items:center;padding:10px 14px}
.row>summary::-webkit-details-marker{display:none}.id{font-weight:600;word-break:break-all}.todo{color:var(--mut);font-size:14px}
.chip{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12.5px;font-weight:600;white-space:nowrap}.t{background:var(--grb);color:var(--gr)}
.s-registered,.s-ready{background:var(--okb);color:var(--ok)}.s-needs_review,.s-needs_input{background:var(--rvb);color:var(--rv)}.s-held,.s-blocked,.s-register_failed,.s-ai_failed{background:var(--hdb);color:var(--hd)}.s-duplicate,.s-skipped,.s-pending,.s-processing{background:var(--grb);color:var(--gr)}
.det{padding:4px 16px 14px;border-top:1px solid var(--line)}.det h4{margin:12px 0 4px;font-size:13px;color:var(--mut);font-weight:600}.det p,.det li{margin:2px 0}.det ul{margin:2px 0;padding-left:20px}
pre{background:var(--code);border-radius:8px;padding:10px 12px;overflow:auto;font:13px/1.45 ui-monospace,Consolas,monospace;margin:4px 0;white-space:pre-wrap;word-break:break-word}
.ans{color:var(--ok);font-weight:600}.warn{color:var(--rv)}.bad{color:var(--hd)}
@media (max-width:640px){.row>summary{grid-template-columns:1fr auto;grid-auto-flow:row}.todo{grid-column:1/-1}}
</style></head><body><div class="w">
<h1>문제 등록 결과</h1><p class="sub" id="sub"></p>
<div class="cards" id="cards"></div>
<div class="bar" id="bar"></div><div class="legend" id="legend"></div>
<div class="filters" id="filters"></div>
<div id="list"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const ST={registered:['등록됨','이미 DB에 저장됨','--ok'],ready:['승인 대기','확인할 것 없음, 승인하면 등록','--ok'],needs_review:['검토 필요','내용을 확인하고 승인','--rv'],needs_input:['입력 필요','서술형 모범 답안을 직접 입력','--rv'],held:['보류','내용을 보완해야 등록 가능','--hd'],blocked:['검사 실패','실패 이유를 고쳐야 등록 가능','--hd'],register_failed:['저장 오류','오류를 확인하고 다시 시도','--hd'],ai_failed:['AI 실패','다시 처리','--hd'],duplicate:['중복','이미 등록된 문제','--gr'],skipped:['제외','사람이 제외함','--gr'],pending:['대기','처리 전','--gr'],processing:['처리 중','','--gr']};
const items=(D.before||D.items).map(x=>x);
const e=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const cnt={},types={'코딩':0,'디버깅':0,'객관식':0,'단답형':0,'주관식':0};items.forEach(i=>{cnt[i.status]=(cnt[i.status]||0)+1;const t=i.payload&&i.payload.problemType;if(t)types[t]=(types[t]||0)+1});
const names=(D.job&&D.job.file_names||[]).join(', ');
document.getElementById('sub').textContent=(names?names+' · ':'')+'문제 '+items.length+'개'+(D.seconds?' · 처리 '+D.seconds+'초':'')+(D.before?'':' (승인 전 상태 없음: 전체 승인 뒤 상태)');
const need=items.filter(i=>!['registered','duplicate','skipped'].includes(i.status)).length;
const card=(n,l)=>'<div class="card"><b>'+n+'</b><span>'+l+'</span></div>';
document.getElementById('cards').innerHTML=card(items.length,'전체 문제')+card(cnt.registered||0,'바로 등록됨')+card(need,'사람이 볼 문제')+card((cnt.held||0)+(cnt.blocked||0)+(cnt.register_failed||0)+(cnt.ai_failed||0),'보류·실패')+Object.entries(types).filter(([t,n])=>n>0||['코딩','디버깅','객관식','단답형','주관식'].includes(t)).map(([t,n])=>card(n,t+' 유형')).join('');
const order=['registered','ready','needs_review','needs_input','held','blocked','register_failed','ai_failed','duplicate','skipped','pending','processing'];
document.getElementById('bar').innerHTML=order.filter(k=>cnt[k]).map(k=>'<i title="'+ST[k][0]+' '+cnt[k]+'" style="width:'+(cnt[k]/items.length*100)+'%;background:var('+ST[k][2]+')"></i>').join('');
document.getElementById('legend').innerHTML=order.filter(k=>cnt[k]).map(k=>'<span><em style="background:var('+ST[k][2]+')"></em>'+ST[k][0]+' '+cnt[k]+'</span>').join('');
let cur='all';
function reasons(i){const r=[];(i.review&&i.review['보류사유'])&&r.push(['bad','보류 사유: '+i.review['보류사유']]);(i.check_fails||[]).forEach(m=>r.push(['bad','검사 실패: '+m]));(i.approval_reasons||[]).forEach(m=>r.push(['warn',m]));((i.review&&i.review['확인필요'])||[]).forEach(m=>r.push(['warn','AI 확인필요: '+m]));if(i.error)r.push(['bad','오류: '+i.error]);return r}
const recBySeq={};items.forEach(i=>{if(i.record)recBySeq[i.seq]=i.record});
const FIELD_LABEL={title:'제목',problemType:'유형',difficulty:'난이도',tags:'태그',description:'설명',problem_condition:'조건',base_code:'제공 코드',reference_codes:'정답 코드',test_cases:'테스트 케이스',options:'보기',correct_answers:'정답 번호',answer_text:'정답'};
function steps(i){
 const p=i.payload||{},r=i.review||{},rec=recBySeq[i.seq]||null,notes=((rec&&rec.intake&&rec.intake['메모'])||[]);
 const ref=(r['참고']||[]).map(String),fill=(r['채움']||[]).filter(x=>x&&x['항목']);
 const fixes=[].concat(r['정리']||[],r['복구']||[]);
 const forced=ref.some(x=>x.includes('AI 호출 전에 보류'));
 const light=ref.some(x=>x.includes('서버가 직접 구성'));
 const S=[];
 S.push(['ok','① 파일 읽기·문제 나누기 (서버)',(rec?(rec['입력종류']||'')+(rec['원본형식']?' · '+rec['원본형식']:rec['표형식']?' · '+rec['표형식']:'')+' 에서 이 문제를 찾음':'이 문제를 찾음')+(notes.length?'<br><span class="warn">⚠ '+notes.map(e).join('<br>⚠ ')+'</span>':'')]);
 if(forced)S.push(['bad','② AI 호출 (건너뜀)','서버가 AI 를 부르기 전에 보류함: '+e(r['보류사유']||'')]);
 else if(i.status==='ai_failed')S.push(['bad','② AI 처리','AI 호출·출력 오류: '+e(i.error||'')]);
 else if(!i.payload&&r['보류사유'])S.push(['bad','② AI 처리 → 보류','AI 가 이 문제를 보류함: '+e(r['보류사유'])]);
 else S.push(['ok','② AI 처리',light?'서버가 엑셀·DB 값으로 문제를 구성하고 AI 는 비어 있는 메타 정보(난이도·태그 등) '+fill.length+'건만 채움':'AI 가 유형을 판정하고 비어 있는 항목 '+fill.length+'건을 채움'+(fill.length?': '+fill.map(x=>e(FIELD_LABEL[x['항목']]||x['항목'])).join(', '):'')]);
 if(i.payload)S.push([fixes.length?'warn':'ok','③ 서버 교정',fixes.length?fixes.length+'건 고침: '+fixes.map(x=>e((x['항목']||'')+' '+(x['변경']||x['처리']||'')).slice(0,60)).join(' / '):'고친 것 없음']);
 if(i.payload){const f=i.check_fails||[],w=i.check_warns||[];S.push([f.length?'bad':(w.length?'warn':'ok'),'④ 서버 검사',f.length?'실패: '+f.map(x=>e(x).slice(0,120)).join(' / '):(w.length?'통과 (경고 '+w.length+'건: '+w.map(x=>e(x).slice(0,80)).join(' / ')+')':'스키마·조건 형식·중복 검사 통과')])}
 const s=ST[i.status]||[i.status,'','--gr'];
 S.push([['registered','ready'].includes(i.status)?'ok':(['needs_review','needs_input'].includes(i.status)?'warn':'bad'),'⑤ 결과','<span class="chip s-'+i.status+'">'+s[0]+'</span> '+e(s[1])+((i.approval_reasons||[]).length?'<br>'+(i.approval_reasons).map(e).join('<br>'):'')]);
 const mark={ok:'✅',warn:'⚠️',bad:'⛔'};
 return '<h4>처리 과정 — 어느 단계에서 무슨 일이 있었나</h4>'+S.map(x=>'<div style="display:grid;grid-template-columns:200px 1fr;gap:8px;padding:5px 0;border-bottom:1px solid var(--line)"><div>'+mark[x[0]]+' '+x[1]+'</div><div'+(x[0]==='bad'?' class="bad"':'')+'>'+x[2]+'</div></div>').join('')}
function original(i){
 const rec=recBySeq[i.seq];if(!rec)return '';
 let h='<h4>올린 파일에서 읽은 내용 (AI 에게 보낸 입력)</h4>';
 if(rec.fields){h+='<div style="font-size:13px">'+Object.entries(rec.fields).filter(([k,v])=>v!==''&&v!==null&&v!==undefined).map(([k,v])=>'<div style="display:grid;grid-template-columns:90px 1fr;gap:8px;padding:3px 0;border-bottom:1px solid var(--line)"><div style="color:var(--mut)">'+e(k)+'</div><div style="white-space:pre-wrap;word-break:break-word">'+e(String(v).slice(0,600))+'</div></div>').join('')+'</div>'}
 if(rec['원본조각'])h+='<pre>'+e(String(rec['원본조각']).slice(0,2500))+(String(rec['원본조각']).length>2500?'\n… (이하 생략)':'')+'</pre>';
 else if(!rec.fields)h+='<p style="color:var(--mut)">읽은 글이 없습니다 (그림만 있는 문제이거나 스캔 문서일 수 있음).</p>';
 return h}
function detail(i){const p=i.payload||{},r=i.review||{};
 const fillMap={};(r['채움']||[]).forEach(x=>{if(x&&x['항목'])fillMap[x['항목']]=x});
 const changed=new Set([].concat(r['정리']||[],r['복구']||[]).map(x=>x&&x['항목']).filter(Boolean));
 const has=v=>!(v===undefined||v===null||v===''||(Array.isArray(v)&&!v.length)||(typeof v==='object'&&!Array.isArray(v)&&!Object.keys(v).length));
 const src=(k,v)=>{const x=fillMap[k];
  if(x)return '<span class="chip s-needs_review" title="근거: '+e(x['근거']||'-')+' / 검증: '+e(x['검증']||'-')+'">AI 작성 · '+e(x['검증']||'-')+'</span>';
  if(changed.has(k))return '<span class="chip t">고침</span>';
  return has(v)?'<span class="chip s-ready">파일 그대로</span>':'<span class="chip t">비어 있음</span>'};
 const row=(label,val,tag)=>'<div style="display:grid;grid-template-columns:120px 1fr;gap:8px;padding:6px 0;border-bottom:1px solid var(--line)"><div style="color:var(--mut);font-size:13px">'+label+(tag?'<br>'+tag:'')+'</div><div>'+val+'</div></div>';
 const none='<span style="color:var(--mut)">(없음)</span>';
 const pre=t=>'<pre>'+e(t)+'</pre>';
 const lang=c=>'<div style="color:var(--mut);font-size:12px">'+e(c.language)+(c.is_main?' · 대표':'')+'</div>';
 const t=p.problemType;let h=steps(i);
 if(!i.payload){h+='<p class="bad">저장될 내용이 없습니다 (보류 또는 처리 실패).</p>'}
 else{
 h+='<h4>저장될 문제 — 기본 틀 전체 (항목마다 누가 채웠는지 표시)</h4>';
 const TI=(i.review&&i.review['제목정보'])||{};
 h+=row('제목',e(p.title)+' <span style="color:var(--mut);font-size:12px">· 영문+숫자 코드 (언어+주제 번호_순번) · 원래 이름: '+e(TI['원래이름']||'-')+(TI['주제번호확실']===false?' · <b class="bad">주제 번호/언어를 확인하세요</b>':'')+'</span>',src('title',p.title));
 h+=row('유형',e(t||'-'),src('problemType',t));
 h+=row('난이도',p.difficulty?e(p.difficulty):none,src('difficulty',p.difficulty));
 h+=row('태그',(p.tags&&p.tags.length)?p.tags.map(x=>'<span class="chip t">'+e(x)+'</span>').join(' '):none,src('tags',p.tags));
 h+=row('채점 방식',e(p.rating_mode||'기본값'),'');
 const sub=fillMap['부제목'],intent=fillMap['문제의도'];
 h+=row('부제목',TI['읽을이름']?e(TI['읽을이름'])+' <span style="color:var(--mut);font-size:12px">· 원래 이름에서 옮김</span>':(sub?e(sub['내용'])+' <span style="color:var(--mut);font-size:12px">· 이름이 없어 AI가 쓴 키워드</span>':none),TI['읽을이름']?'':src('부제목',sub));
 h+=row('문제의도',intent?e(intent['내용']):none,src('문제의도',intent));
 h+=row('설명',p.description?pre(p.description):none,src('description',p.description));
 h+=row('조건',(p.problem_condition&&p.problem_condition.length)?'<ul style="margin:0;padding-left:18px">'+p.problem_condition.map(c=>'<li>'+e(c)+'</li>').join('')+'</ul>':none,src('problem_condition',p.problem_condition));
 if(t==='코딩'||t==='디버깅'){
  if(t==='디버깅')h+=row('제공 코드',(p.base_code&&p.base_code.length)?p.base_code.map(c=>lang(c)+pre(c.code)).join(''):none,src('base_code',p.base_code));
  h+=row('정답 코드',(p.reference_codes&&p.reference_codes.length)?p.reference_codes.map(c=>lang(c)+pre(c.code)).join(''):none,src('reference_codes',p.reference_codes));
  h+=row('테스트 케이스',(p.test_cases&&p.test_cases.length)?p.test_cases.map((c,k)=>'<div style="color:var(--mut);font-size:12px">케이스 '+(k+1)+(c.is_hidden?' · 숨김':' · 공개')+'</div>'+pre('입력: '+(c.input||'')+'\n출력: '+(c.expected_output||''))).join(''):none,src('test_cases',p.test_cases));
 }else if(t==='객관식'){
  const ca=p.correct_answers||[];
  h+=row('보기',(p.options&&p.options.length)?'<ol style="margin:0;padding-left:20px">'+p.options.map((o,k)=>'<li'+(ca.includes(k)?' class="ans"':'')+'>'+e(o)+(ca.includes(k)?'  ← 정답':'')+'</li>').join('')+'</ol>':none,src('options',p.options));
  h+=row('정답 번호',ca.length?ca.map(k=>k+1).join(', ')+'번':none,src('correct_answers',ca));
 }else if(t==='단답형'){
  const a=p.answer_text;
  h+=row('정답',!has(a)?none:pre(typeof a==='string'?a:Array.isArray(a)?a.join('\n'):Object.entries(a).map(([k,v])=>k+'번: '+[].concat(v).join(' / ')).join('\n')),src('answer_text',a));
 }else if(t==='주관식'){
  h+=row('모범 답안',p.answer_text?pre(p.answer_text):'<span class="warn">(비어 있음 — 사람이 직접 입력)</span>',src('answer_text',p.answer_text));
  h+=row('채점 기준',p.grading_criteria?pre(Array.isArray(p.grading_criteria)?p.grading_criteria.join('\n'):p.grading_criteria):none,'');
 }
 }
 h+=original(i);
 const rs=reasons(i);if(rs.length)h+='<h4>보류·확인 이유 전체</h4><ul>'+rs.map(x=>'<li class="'+x[0]+'">'+e(x[1])+'</li>').join('')+'</ul>';
 const fill=(r['채움']||[]).filter(x=>x&&x['항목']);
 if(fill.length)h+='<h4>AI 가 입력한 것 ('+fill.length+'건) — 파일에 없어서 AI 가 채움</h4><ul>'+fill.map(x=>'<li><b>'+e(FIELD_LABEL[x['항목']]||x['항목'])+'</b>: '+e(typeof x['내용']==='string'?x['내용']:JSON.stringify(x['내용'])).slice(0,300)+' <span style="color:var(--mut)">· 근거: '+e(x['근거']||'-').slice(0,80)+' · 검증: '+e(x['검증']||'-')+'</span></li>').join('')+'</ul>';
 else h+='<h4>AI 가 입력한 것</h4><p style="color:var(--mut)">없음 — 파일의 값을 그대로 옮김</p>';
 const fx=[].concat((r['정리']||[]).map(x=>['정리',x]),(r['복구']||[]).map(x=>['복구',x]));
 if(fx.length)h+='<h4>AI·서버가 고친 것</h4><ul>'+fx.map(([k,x])=>'<li>['+k+'] '+e(x['항목']||'')+': '+e(x['변경']||x['처리']||'').slice(0,200)+' <span style="color:var(--mut)">'+e(x['이유']||'')+'</span></li>').join('')+'</ul>';
 if((r['조언']||[]).length)h+='<h4>AI 의 조언 (적용하지 않음)</h4><ul>'+r['조언'].map(x=>'<li>['+e(x['중요도']||'')+'] '+e(x['대상']||'')+': '+e(x['문제점']||'')+' → '+e(x['제안']||'').slice(0,200)+'</li>').join('')+'</ul>';
 if((r['참고']||[]).length)h+='<h4>참고</h4><ul>'+r['참고'].map(x=>'<li style="color:var(--mut)">'+e(x)+'</li>').join('')+'</ul>';
 if(i.ai_filled&&i.ai_filled.length)h+='<h4 class="warn">AI 가 직접 푼 정답 (사후 점검 대상)</h4><ul>'+i.ai_filled.map(x=>'<li>'+e(typeof x==='string'?x:JSON.stringify(x))+'</li>').join('')+'</ul>';
 return h}
function draw(){const L=document.getElementById('list');L.innerHTML=items.filter(i=>cur==='all'||i.status===cur).map(i=>{const p=i.payload||{},s=ST[i.status]||[i.status,'','--gr'],rs=reasons(i);
 return '<details class="row"><summary><span class="id">'+e(i.result_id||i.source_key)+'</span><span>'+(p.problemType?'<span class="chip t">'+e(p.problemType)+'</span>':'')+'</span><span><span class="chip s-'+i.status+'">'+s[0]+'</span></span><span class="todo">'+(((i.review&&i.review['채움'])||[]).length?'<b>AI 입력 '+i.review['채움'].length+'건</b> · ':'')+e(s[1])+(rs.length?' — '+e(rs[0][1]).slice(0,70):'')+'</span></summary><div class="det">'+detail(i)+'</div></details>'}).join('')||'<p style="color:var(--mut)">해당하는 문제가 없습니다.</p>'}
const F=document.getElementById('filters');
function btns(){F.innerHTML=[['all','전체 '+items.length]].concat(order.filter(k=>cnt[k]).map(k=>[k,ST[k][0]+' '+cnt[k]])).map(x=>'<button aria-pressed="'+(cur===x[0])+'" data-k="'+x[0]+'">'+x[1]+'</button>').join('')}
F.onclick=ev=>{const k=ev.target.dataset.k;if(k){cur=k;btns();draw()}};btns();draw();
</script></body></html>"""


def build(src, dst=None):
    d = json.load(open(src, encoding="utf-8"))
    data = json.dumps(d, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    dst = dst or os.path.splitext(src)[0] + "_보고서.html"
    open(dst, "w", encoding="utf-8").write(PAGE.replace("__DATA__", data))
    return dst


if __name__ == "__main__":
    if len(sys.argv) < 2: print(__doc__); sys.exit(2)
    print("보고서:", os.path.abspath(build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
