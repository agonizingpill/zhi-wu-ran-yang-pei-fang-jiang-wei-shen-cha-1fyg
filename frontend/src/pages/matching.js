import {store,refresh} from '../store.js';import {api,session} from '../api.js';import {heading} from '../components/common.js';import {escape,decimal,formData,notify,localTime} from '../utils.js';
const labels={open:'待主管确认',insufficient:'证据不足未推荐',confirmed:'已确认发样',rejected:'整单拒绝可重算'};
const pct=p=>p===null||p===undefined?'—':decimal(p*100,1)+'%';
const batchCode=id=>store.batches.find(b=>b.id===id)?.code||'#'+id;
function metrics(m){
 if(!m||!m.trained_records)return '<div class="rule">本次匹配未留下训练记录。</div>';
 const head=`<div class="metricline"><div>训练样本<strong>${m.trained_records} 条（接受${m.accepted} / 争议${m.disputed}）</strong></div><div>推荐门限<strong>接受概率 ≥ ${decimal(m.threshold,2)}</strong></div></div>`;
 if(!m.sufficient)return head+`<div class="rule">${escape(m.insufficient_reason)}</div>`;
 return head+`<div class="metricline"><div>分组检验 logloss<strong>${m.cv.logloss}（基准 ${m.baseline.logloss}）</strong></div><div>Brier<strong>${m.cv.brier}（基准 ${m.baseline.brier}）</strong></div><div>命中率<strong>${pct(m.cv.accuracy)}</strong></div></div><p class="hint">${escape(m.cv_note)}；模型 P=σ(w₀+w₁·ΔE)，w=[${m.coefficients.map(x=>decimal(x,3)).join(', ')}]</p>`;
}
function sources(m){
 if(!m||!m.sources||!m.sources.length)return '';
 return `<details><summary>训练依据：${m.sources.length} 条已签收结论（历史结论不改写）</summary><table><thead><tr><th>运单</th><th>客户</th><th>生产缸</th><th>ΔE</th><th>结论</th></tr></thead><tbody>${m.sources.map(s=>`<tr><td>${escape(s.tracking)}</td><td>${escape(s.customer)}</td><td>${escape(s.batch_code)}</td><td>${decimal(s.delta_e,3)}</td><td>${s.conclusion==='accepted'?'接受':'争议'}</td></tr>`).join('')}</tbody></table></details>`;
}
function candidates(item){
 if(!item.candidates.length)return '';
 return `<details><summary>候选评估与落选原因（${item.candidates.length} 口缸）</summary><table><thead><tr><th>缸号</th><th>与客户目标 ΔE</th><th>接受概率</th><th>结果</th></tr></thead><tbody>${item.candidates.map(c=>`<tr><td>${escape(c.batch_code)}</td><td>${decimal(c.delta_e,3)}</td><td>${pct(c.probability)}</td><td>${c.chosen?'<strong>本方案选中</strong>':escape(c.reason)}</td></tr>`).join('')}</tbody></table></details>`;
}
function runCard(run){
 const m=run.model_snapshot;
 const rows=run.items.map(i=>`<tr><td>${escape(i.customer)}</td><td>${decimal(i.target_snapshot.l)} / ${decimal(i.target_snapshot.a)} / ${decimal(i.target_snapshot.b)}</td><td>${i.batch_id?escape(batchCode(i.batch_id)):'—'}</td><td>${pct(i.probability)}</td><td>${i.batch_id?(run.state==='confirmed'?'已生成发样单 #'+i.dispatch_id:'待主管确认'):escape(i.reason)}</td></tr>`).join('');
 const actions=[];
 if(run.state==='open'&&run.items.some(i=>i.batch_id))actions.push(`<button class="primary" data-confirm="${run.id}" ${session().role!=='admin'?'disabled':''}>主管确认，生成真实发样单</button>`);
 if(run.state!=='confirmed')actions.push(`<button data-rematch="${run.id}" ${session().role==='viewer'?'disabled':''}>按剩余缸重算</button>`);
 return `<article class="trial dispatch"><div class="code">方案 #${run.id} · ${escape(run.created_by)} · ${localTime(run.created_at)}${run.confirmed_by?' · 确认人 '+escape(run.confirmed_by):''}</div><h3>联合匹配方案 <span class="status ${run.state==='confirmed'?'approved':run.state==='rejected'||run.state==='insufficient'?'rejected':''}">${labels[run.state]}</span></h3>${metrics(m)}${run.reject_reason?`<div class="rule">${escape(run.reject_reason)}</div>`:''}<table><thead><tr><th>客户</th><th>目标 L/a/b</th><th>推荐缸</th><th>接受概率</th><th>说明</th></tr></thead><tbody>${rows}</tbody></table>${run.items.map(candidates).join('')}${sources(m)}<div class="actions">${actions.join('')}</div></article>`;
}
export function render(){
 const targets=store.targets.map(t=>`<tr><td>${escape(t.customer)}</td><td>${decimal(t.l)} / ${decimal(t.a)} / ${decimal(t.b)}</td><td>${escape(t.note)}</td></tr>`).join('');
 return heading('10','让签收数据先说话，再决定发哪口缸','厂内 ΔE 合格仍可能被客户拒收。用已签收发样的接受与争议结论训练客户接受概率，按生产缸分组检验；证据不足不给推荐。多客户目标色从已签放未发样缸联合匹配，每客一缸、同缸不分两客。')
 +`<div class="split"><section class="panel"><h2>客户目标色录入</h2><form id="target-form"><label>客户名称<input name="customer" placeholder="北野户外 / 面料组" required></label><div class="grid3"><label>目标 L*<input name="l" type="number" step=".01" min="0" max="100" value="40" required></label><label>目标 a*<input name="a" type="number" step=".01" value="-6" required></label><label>目标 b*<input name="b" type="number" step=".01" value="-18" required></label></div><label>用途备注<input name="note" placeholder="冲锋衣外壳季色"></label><button class="primary" ${session().role==='viewer'?'disabled':''}>录入客户目标色</button></form><table><thead><tr><th>客户</th><th>目标 L/a/b</th><th>备注</th></tr></thead><tbody>${targets||'<tr><td colspan="3">尚未录入客户目标色。</td></tr>'}</tbody></table></section><section class="panel"><h2>发起联合匹配</h2><p class="hint">对已录入的全部客户目标色发起一次联合匹配：模型用已签收结论训练，按生产缸分组留一检验；候选为当前已签放且未发样的生产缸。每客至多一口缸，同一口缸不会分给两家客户；概率低于门限或训练证据不足时不给推荐。</p><button id="run-btn" class="primary" ${session().role==='viewer'?'disabled':''}>发起匹配</button><div class="rule">主管确认后系统在同一事务生成真实发样单；若有缸已被别处发走，整单拒绝并可按剩余缸重算。中断重试不会新增发样单。</div></section></div><section class="panel"><h2>匹配方案与检验表现</h2>${store.runs.map(runCard).join('')||'<div class="empty">先录入客户目标色，再发起第一次联合匹配。</div>'}</section>`;
}
export function bind(render){
 async function save(path,body,msg){try{await api(path,'POST',body);await refresh();render();notify(msg);}catch(e){notify(e.message);}}
 document.querySelector('#target-form').onsubmit=e=>{e.preventDefault();let d=formData(e.target);['l','a','b'].forEach(k=>d[k]=Number(d[k]));save('/customer-targets',d,'客户目标色已录入');};
 document.querySelector('#run-btn').onclick=()=>save('/match-runs',{},'匹配方案已生成，请查看概率与检验表现');
 document.querySelectorAll('[data-confirm]').forEach(b=>b.onclick=()=>save('/match-runs/'+b.dataset.confirm+'/confirm',{},'方案已确认，真实发样单已生成'));
 document.querySelectorAll('[data-rematch]').forEach(b=>b.onclick=()=>save('/match-runs/'+b.dataset.rematch+'/rematch',{},'已按剩余候选缸重新匹配'));
}
