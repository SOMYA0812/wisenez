'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {review:'Awaiting your review',approved:'Approved · ready to execute',completed:'Completed',partial:'Needs attention',stale:'Preview expired',rejected:'Rejected',preparation_failed:'Preparation stopped',unsupported:'Outside this MVP',preparing:'Preparing',executing:'Executing'};
const modeLabels = {sample:'Sample demo',openrouter:'Live OpenRouter',replay:'Recorded replay'};
const notes = {sample:'Sample demo — deterministic outputs. No live AI calls.',openrouter:'Live OpenRouter — three separate AI roles. Up to 20 live preparations per day for this demo.',replay:'Recorded replay — saved live outputs. Brief, selection, policy, and source records must match exactly.'};
let state = null;
let activeId = new URLSearchParams(location.search).get('run') || '';
let selected = new Set();
let selectedInitialized = false;
let currentTab = ['workspace','review','execution','impact'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'workspace';
let busy = false;
let dirty = false;
let requestSequence = 0;

async function api(path, body) {
  const response = await fetch('/api/' + path, {method:body ? 'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body ? {'Content-Type':'application/json','X-Wisnez-Request':'1'} : {},body:body ? JSON.stringify(body) : undefined});
  let data;
  try { data = await response.json(); } catch { throw new Error('The server did not return a complete response. Refresh to check saved progress.'); }
  if (!response.ok) {
    if (response.status === 401 && path !== 'login') showLogin();
    const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(' · ') : data.detail;
    throw new Error(detail || 'This request could not be completed. Refresh and retry.');
  }
  return data;
}
function mutation(body) { return {operation_id:crypto.randomUUID(),...body}; }
function notice(message, error=false) {
  $('#notice').textContent = message;
  $('#notice').classList.toggle('error-notice', error);
  $('#notice').hidden = !message;
}
function setBusy(value, message='Saving your work…') {
  busy = value;
  $('#busy').hidden = !value;
  $('#busy-text').textContent = message;
  document.body.setAttribute('aria-busy', String(value));
  $$('button').forEach(b => { if (value) { b.dataset.wasDisabled = String(b.disabled); b.disabled = true; } else if (b.dataset.wasDisabled !== undefined) { b.disabled = b.dataset.wasDisabled === 'true'; delete b.dataset.wasDisabled; } });
}
async function work(message, fn) {
  if (busy) return;
  notice(''); setBusy(true,message);
  try { await fn(); } catch (error) { notice(error.message,true); } finally { setBusy(false); updateApprovalControls(); }
}
function showLogin() {
  $('#landing').hidden = true; $('#dashboard').hidden = true; $('#login').hidden = false;
}
function tab(name) {
  currentTab = name;
  $$('.view').forEach(v => v.hidden = v.id !== 'view-' + name);
  $$('[data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
  const url = new URL(location.href); url.hash = name; history.replaceState(null,'',url);
}
function setRun(id) {
  activeId = id || '';
  const url = new URL(location.href);
  if (activeId) url.searchParams.set('run',activeId); else url.searchParams.delete('run');
  history.replaceState(null,'',url);
}
async function refresh() {
  const sequence = ++requestSequence;
  const data = await api('state' + (activeId ? '?run=' + encodeURIComponent(activeId) : ''));
  if (sequence !== requestSequence) return;
  state = data; dirty = false;
  $('#landing').hidden = true; $('#login').hidden = true; $('#dashboard').hidden = false;
  if (!selectedInitialized) { selected = new Set(state.leads.slice(0,5).map(l => l.id)); selectedInitialized = true; }
  render();
}
function fmtDate(date) { const d = new Date(date); return Number.isNaN(+d) ? date : d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); }
function empty(title, message) { return `<div class="panel empty"><span class="eyebrow">YOUR NEXT CHAPTER</span><h2>${esc(title)}</h2><p>${esc(message)}</p><button type="button" data-go="workspace">Go to workspace ↗</button></div>`; }
function bindGo() { $$('[data-go]').forEach(b => b.onclick = () => tab(b.dataset.go)); }

function render() {
  const run = state.active, plan = run?.plan, proposals = plan?.proposals || [];
  $('#hero-prepared').textContent = proposals.length;
  $('#hero-completed').textContent = run?.counts.completed || 0;
  $('#hero-blocked').textContent = proposals.filter(p => p.blocked_reasons.length).length;
  $('#hero-state').textContent = run ? labels[run.state] || run.state : 'Ready to begin';
  $('#review-count').textContent = run?.state === 'review' ? '· ' + proposals.filter(p => !p.blocked_reasons.length).length : '';
  $('#run-select').innerHTML = '<option value="">New workflow</option>' + state.runs.map(r => `<option value="${esc(r.id)}">${esc(r.id.slice(0,6))} · ${esc(labels[r.state] || r.state)} · ${esc(modeLabels[r.mode] || r.mode)}</option>`).join('');
  $('#run-select').value = activeId;
  $('#storage-note').textContent = state.persistent ? 'Private cloud storage · progress saved' : 'Local storage · progress saved';
  $('#mode-note').textContent = notes[$('#mode').value] + ($('#mode').value === 'openrouter' ? ' Model: ' + state.model + '.' + (state.live_available ? '' : ' API key is not configured.') : '');
  renderLeads(); renderMemory(); renderActivity(); renderReview(); renderExecution(); renderImpact(); bindGo(); tab(currentTab);
  if (run?.error) notice(run.error,true);
}
function renderLeads() {
  $('#leads').innerHTML = state.leads.map(l => `<tr><td><input aria-label="Select ${esc(l.name)}" data-select="${esc(l.id)}" type="checkbox" ${selected.has(l.id)?'checked':''}></td><td><strong>${esc(l.name)}</strong><small>${esc(l.email || 'No email address')}</small></td><td>${esc(l.company)}</td><td><span class="status-badge">${esc(l.opted_out ? 'Opted out' : l.status)}</span></td><td><button class="quiet" data-inspect="${esc(l.id)}" type="button" aria-label="Inspect ${esc(l.name)}">↗</button></td></tr>`).join('');
  $('#selection-count').textContent = selected.size + ' / 5 selected';
  $$('[data-select]').forEach(input => input.onchange = () => {
    if (input.checked && selected.size >= 5) { input.checked = false; notice('Select at most five leads per workflow.',true); return; }
    if (input.checked) selected.add(input.dataset.select); else selected.delete(input.dataset.select);
    $('#selection-count').textContent = selected.size + ' / 5 selected';
  });
  $$('[data-inspect]').forEach(b => b.onclick = () => inspectLead(b.dataset.inspect));
}
function renderMemory() {
  const p = state.policy;
  $('#memory').innerHTML = `<div class="memory-grid"><div><strong>Services offered</strong><p>${esc(p.services.join(', '))}.</p></div><div><strong>Qualification rules</strong><p>Hot: offered service, budget ≥ ₹${p.minimum_budget.toLocaleString()}, and timeline ≤ ${p.urgent_days} days. Missing facts remain unknown.</p></div><div><strong>Contact boundaries</strong><p>Block opt-outs, invalid addresses, and conflicting identities.</p></div><div><strong>Human control</strong><p>All CRM changes and simulated email require approval of the exact preview.</p></div></div><p class="policy-note">${esc(p.business_name)} · Policy version ${p.version} · Human-authored rules. ${esc(p.instructions)}</p>`;
}
function renderActivity() {
  const events = (state.active?.events || []).filter(e => ['Planner','Lead analyst','Outreach writer','Supervisor'].includes(e.stage));
  $('#activity').innerHTML = events.length ? events.slice(-5).map(e => `<div class="activity-line"><span class="event-dot"></span><div><strong>${esc(e.stage)}</strong><small>${esc(e.message)}</small></div></div>`).join('') : '<p class="muted">Give your team a brief to get started.</p>';
}
function renderReview() {
  const r = state.active;
  if (!r?.plan) { $('#review-content').innerHTML = empty('A clear view, before every action.',r?.error || 'Prepare a workflow to see source evidence, CRM changes, and personalised follow-ups.'); return; }
  const eligible = r.plan.proposals.filter(p => !p.blocked_reasons.length);
  const blocked = r.plan.proposals.filter(p => p.blocked_reasons.length);
  const editable = ['review','approved'].includes(r.state);
  const card = (p,index) => {
    const bad = p.blocked_reasons.length > 0;
    const fields = ['status','qualification','summary'].filter(k => Object.hasOwn(p.crm_after,k));
    return `<details class="review-card" ${index===0?'open':''}><summary><div><h3>${esc(p.source.name)} <span class="muted">· ${esc(p.source.company)}</span></h3><p>${esc(p.source.email)} · ${esc(p.lead_id)}</p></div><span class="qualification ${bad?'blocked':esc(p.qualification)}">${bad?'Blocked':esc(p.qualification)}</span></summary><div class="review-card-content">${bad?`<div class="exception"><strong>Exception inbox · no actions permitted</strong><ul>${p.blocked_reasons.map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul></div>`:''}<blockquote class="quote">${esc(p.source.enquiry)}</blockquote><p class="muted">${esc(p.assessment.summary)}</p><p class="evidence"><b>Company rule:</b> ${esc(p.rule)}</p>${p.assessment.evidence.map(e=>`<p class="evidence"><b>${esc(e.field)}:</b> “${esc(e.quote)}”</p>`).join('')}${p.missing.length?`<p class="evidence"><b>Missing facts:</b> ${esc(p.missing.join(', '))}</p>`:''}<div class="review-grid"><div><h4>PROPOSED CRM CHANGES ${!p.write_crm || bad ? '· NOT SCHEDULED':''}</h4><table class="crm-table"><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>${fields.map(k=>`<tr><td>${esc(k)}</td><td>${esc(p.source[k] || '—')}</td><td>${esc(p.crm_after[k])}</td></tr>`).join('')}</tbody>${editable&&!bad&&p.write_crm?`<label>CRM summary<textarea data-lead="${esc(p.lead_id)}" data-field="summary" maxlength="800" required>${esc(p.crm_after.summary)}</textarea></label>`:''}</div><div class="draft-editor"><h4>EMAIL PREVIEW ${bad?'· BLOCKED':!p.queue_email?'· NOT SCHEDULED':''}</h4>${p.draft?`<p>To: ${esc(p.source.email)}</p>${editable&&!bad?`<label>Subject · ${esc(p.source.company)}<input data-lead="${esc(p.lead_id)}" data-field="subject" value="${esc(p.draft.subject)}" maxlength="200" required></label><label>Message · ${esc(p.source.company)}<textarea data-lead="${esc(p.lead_id)}" data-field="body" maxlength="5000" required>${esc(p.draft.body)}</textarea></label>`:`<h4>${esc(p.draft.subject)}</h4><div class="read-only-draft">${esc(p.draft.body)}</div>`}`:'<p>No email drafted for this lead.</p>'}</div></div></div></details>`;
  };
  $('#review-content').innerHTML = `<div class="panel"><div class="view-intro"><div><span class="eyebrow">LOOK CLOSELY. THEN DECIDE.</span><h2>Your exact execution preview.</h2><p>Version ${r.version} · ${esc(modeLabels[r.mode] || r.mode)} · ${esc(labels[r.state])}</p><span class="hash">Action hash · ${esc(r.plan_hash)}</span></div><span class="badge">${eligible.filter(p=>p.write_crm||p.queue_email).length} eligible · ${blocked.length} blocked</span></div><p class="muted">${esc(r.plan.task_plan.explanation)}</p><div class="risk-legend"><span>Automatic · analysis & drafts</span><span>Approval required · CRM & outbox</span><span>Blocked · prohibited contacts</span></div><div id="draft-editors">${eligible.map(card).join('')}${blocked.length?'<h3>Exception inbox</h3>':''}${blocked.map(card).join('')}</div><p id="dirty-warning" class="dirty-warning" hidden>Unsaved changes. Save edits and review the new version before approval or execution.</p>${editable?'<button id="save-edits" type="button">Save preview edits</button>':''}<div class="approval-panel"><h3>${r.state==='approved'?'Approved. Ready when you are.':r.state==='review'?'The final say belongs to you.':esc(labels[r.state])}</h3><p>${r.state==='approved'?`Approved by ${esc(r.approved_by)}. Any edit requires fresh approval.`:'Approval covers only the saved recipients, drafts, and CRM changes shown in this version.'}</p>${editable?`<label for="operator">Approving person's name</label><input id="operator" maxlength="120" placeholder="Your name" value="${esc(sessionStorage.getItem('wisnez-operator') || '')}"><label class="check"><input id="confirm-approval" type="checkbox">I have saved my edits and reviewed the exact recipients, full drafts, and CRM changes.</label><div class="button-row"><button id="approve" class="primary" type="button" ${r.state!=='review'?'disabled':''}>Approve this version ↗</button><button id="reject" class="quiet" type="button">Reject this version</button>${r.state==='approved'?'<button data-go="execution" type="button">Go to execution ↗</button>':''}</div>`:`<button data-go="${r.state==='completed'||r.state==='partial'?'execution':'workspace'}" type="button">${r.state==='completed'||r.state==='partial'?'View execution results':'Prepare a new workflow'} ↗</button>`}<small>Approval identity is the signed-in workspace operator's audit label. No real email is delivered.</small></div></div>`;
  $$('[data-field]').forEach(input => input.oninput = () => { dirty=true; $('#dirty-warning').hidden=false; if ($('#confirm-approval')) $('#confirm-approval').checked=false; updateApprovalControls(); });
  if ($('#save-edits')) $('#save-edits').onclick = saveEdits;
  if ($('#approve')) $('#approve').onclick = () => decision('approve');
  if ($('#reject')) $('#reject').onclick = () => decision('reject');
  if ($('#confirm-approval')) $('#confirm-approval').onchange = updateApprovalControls;
  if ($('#operator')) $('#operator').oninput = updateApprovalControls;
  updateApprovalControls();
}
function updateApprovalControls() {
  if ($('#approve')) $('#approve').disabled = busy || dirty || state?.active?.state !== 'review' || !$('#confirm-approval')?.checked || !$('#operator')?.value.trim();
  if ($('#execute')) $('#execute').disabled = busy || dirty || !['approved','partial'].includes(state?.active?.state);
  if ($('#save-edits')) $('#save-edits').disabled = busy || !dirty;
}
async function saveEdits() {
  const changes={};
  for (const input of $$('[data-field]')) {
    if (!input.reportValidity()) return;
    (changes[input.dataset.lead] ||= {})[input.dataset.field]=input.value;
  }
  await work('Saving a new preview version…',async()=> {
    await api(`runs/${activeId}/edit`,mutation({version:state.active.version,changes}));
    await refresh(); notice('Preview saved. Any previous approval is invalid. Review and approve the current version.');
  });
}
async function decision(choice) {
  const operator=$('#operator').value.trim();
  if (!operator) { notice('Enter your name to record your decision.',true); return; }
  await work(choice==='approve'?'Recording your approval…':'Recording your rejection…',async()=> {
    const r=state.active;
    await api(`runs/${activeId}/${choice}`,mutation({version:r.version,plan_hash:r.plan_hash,operator,confirmed:$('#confirm-approval').checked}));
    sessionStorage.setItem('wisnez-operator',operator); await refresh();
    notice(choice==='approve'?'This exact version is approved. Open Execution when you are ready.':'Version rejected. No business changes executed.');
  });
}
function eventsHTML(events) { return events.map(e=>`<div class="event-row"><time datetime="${esc(e.created_at)}">${esc(fmtDate(e.created_at))}</time><div><strong>${esc(e.stage)}${e.lead_id?' · '+esc(e.lead_id):''}</strong><span class="event-kind">${esc(e.kind)}</span></div><p>${esc(e.message)}</p></div>`).join(''); }
function renderExecution() {
  const r=state.active;
  if (!r) { $('#execution-content').innerHTML=empty('Ready when you are.','Prepare and approve a workflow before any CRM change or simulated message can execute.'); return; }
  const c=r.counts;
  const messages=state.outbox.filter(m=>m.run_id===r.id);
  $('#execution-content').innerHTML=`<div class="panel"><div class="view-intro"><div><span class="eyebrow">FROM APPROVAL TO ACTION</span><h2>Controlled execution.</h2><p>${esc(labels[r.state])} · Version ${r.version} · ${esc(modeLabels[r.mode]||r.mode)}</p></div><span class="badge">Simulated tools only</span></div><div class="result-grid"><div><strong>${c.completed}</strong><span>Completed lead workflows</span></div><div><strong>${c.pending}</strong><span>Pending</span></div><div><strong>${c.failed}</strong><span>Need attention</span></div><div><strong>${messages.length}</strong><span>Simulated messages queued</span></div></div><p class="muted">Each lead's CRM change and outbox entry commit together. Completed actions are preserved during retries.</p><div class="execution-tools"><label>Demo failure simulation<select id="failure"><option value="none">No simulated failure</option><option value="temporary">Temporary CRM failure · retry once</option><option value="persistent">Persistent CRM failure · exception</option><option value="outbox">Temporary outbox failure · rollback & retry</option></select></label><button id="execute" type="button" class="primary" ${!['approved','partial'].includes(r.state)?'disabled':''}>${r.state==='partial'?'Retry unfinished actions':'Execute approved actions'} ↗</button></div>${!['approved','partial','completed'].includes(r.state)?'<p class="muted">Execution requires current human approval. Open Review first.</p>':''}${r.actions.length?`<div class="table-scroll"><table><thead><tr><th>Lead</th><th>Result</th><th>Attempts</th><th>Action ID</th></tr></thead><tbody>${r.actions.map(a=>`<tr><td>${esc(a.lead_id)}</td><td>${esc(a.state)}</td><td>${a.attempts}</td><td>${esc(a.id)}</td></tr>`).join('')}</tbody></table></div>`:''}<h3 class="spaced-heading">Execution trail</h3>${eventsHTML(r.events)}<h3 class="spaced-heading">Simulated outbox</h3><p class="muted">Simulated — no email delivered. These are the exact approved messages.</p><div class="outbox-list">${messages.map(m=>`<article class="outbox-message"><p>To: ${esc(m.recipient)}</p><h3>${esc(m.subject)}</h3><details><summary>View full message</summary><pre>${esc(m.body)}</pre></details><small>${esc(fmtDate(m.created_at))}</small></article>`).join('')||'<p class="muted">No messages queued for this workflow.</p>'}</div></div>`;
  $('#execute').onclick=()=>work('Executing the approved version with bounded recovery…',async()=>{
    const r=state.active;
    await api('execute/'+activeId,mutation({version:r.version,plan_hash:r.plan_hash,failure:$('#failure').value}));
    await refresh(); notice(state.active.state==='completed'?'Approved actions completed. CRM and simulated outbox are saved.':state.active.state==='stale'?'Source data changed. Prepare a new preview and obtain fresh approval.':'Independent leads finished. Review the exception and retry unfinished actions when ready.',state.active.state==='stale');
  });
  updateApprovalControls();
}
function renderImpact() {
  const m=state.impact;
  $('#impact-content').innerHTML=`<div class="panel"><span class="eyebrow">SMALL ACTIONS. VISIBLE PROGRESS.</span><h2>Business impact, honestly counted.</h2><p class="muted">Only successfully committed lead workflows count as completed.</p><div class="impact-grid"><div><strong>${m.completed}</strong><span>Completed lead workflows</span></div><div><strong>${m.blocked}</strong><span>Distinct contacts blocked</span></div><div><strong>${m.recovered}</strong><span>Recovered tool failures</span></div><div><strong>${m.estimated_minutes}<small> min</small></strong><span>Estimated manual effort automated</span></div></div><p class="impact-note">Estimate = ${m.minutes_per_lead} minutes × ${m.completed} completed lead workflows. The ${m.minutes_per_lead}-minute assumption is illustrative; this is not measured time savings or generated revenue. Blocked contacts are distinct lead records across saved previews.</p><h3 class="spaced-heading">Human decision history</h3><div class="table-scroll"><table><thead><tr><th>Operator</th><th>Decision</th><th>Version</th><th>Workflow</th><th>When</th></tr></thead><tbody>${state.approvals.map(a=>`<tr><td>${esc(a.operator)}</td><td>${esc(a.decision)}</td><td>${a.version}</td><td>${esc(a.run_id.slice(0,8))}</td><td>${esc(fmtDate(a.created_at))}</td></tr>`).join('')||'<tr><td colspan="5">No human decisions recorded yet.</td></tr>'}</tbody></table></div></div>`;
}
function inspectLead(id) {
  const lead=state.leads.find(l=>l.id===id), form=$('#source-form');
  for (const name of ['id','version','name','company','email','enquiry']) form.elements[name].value=lead[name];
  form.elements.opted_out.checked=lead.opted_out;
  form.elements.identity_conflict.checked=lead.identity_conflict;
  $('#customer-history').innerHTML='<strong>Customer history</strong>'+ (lead.history.map(h=>`<p>${esc(h)}</p>`).join('')||'<p>No previous interactions recorded.</p>');
  $('#lead-dialog').showModal();
}
$('#login-form').onsubmit=async event=>{
  event.preventDefault(); const button=event.currentTarget.querySelector('button'); button.disabled=true;
  $('#login-error').textContent='';
  try { await api('login',{code:$('#access-code').value}); $('#access-code').value=''; await refresh(); }
  catch(error) { $('#login-error').textContent=error.message; } finally { button.disabled=false; }
};
$$('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
$('#mode').value=localStorage.getItem('wisnez-mode')||'sample';
$('#mode').onchange=()=>{localStorage.setItem('wisnez-mode',$('#mode').value); if(state) $('#mode-note').textContent=notes[$('#mode').value]+($('#mode').value==='openrouter'?' Model: '+state.model+'.':'');};
$('#refresh').onclick=()=>work('Loading saved progress…',async()=>{await refresh();notice('Saved progress refreshed.');});
$('#run-select').onchange=()=>work('Opening saved workflow…',async()=>{setRun($('#run-select').value);await refresh();});
$('#logout').onclick=()=>work('Locking your workspace…',async()=>{await api('logout',{});state=null;showLogin();});
$('#prepare-form').onsubmit=event=>{
  event.preventDefault();
  if(!selected.size){notice('Select at least one lead.',true);return;}
  const mode=$('#mode').value;
  work(mode==='openrouter'?'Planner → lead analyst → outreach writer. Live AI preparation may take a minute…':'Preparing the workflow and checking company policies…',async()=>{
    const result=await api('prepare',mutation({request:$('#brief').value,lead_ids:[...selected],mode}));
    setRun(result.run_id);await refresh();tab('review');
    if(state.active.state==='review') notice('Preview ready. No CRM changes or messages have executed.');
  });
};
$('#new-lead-form').onsubmit=event=>{
  event.preventDefault();const form=event.currentTarget;const fields=Object.fromEntries(new FormData(form));
  work('Saving the fresh enquiry…',async()=>{const result=await api('leads',mutation(fields));if(selected.size<5)selected.add(result.lead_id);form.reset();await refresh();notice('Enquiry saved. Select it in the lead workspace to prepare a workflow.');});
};
$('#source-form').onsubmit=event=>{
  event.preventDefault();const form=event.currentTarget, values=Object.fromEntries(new FormData(form));
  const {id,...fields}=values;fields.version=Number(fields.version);fields.opted_out=form.elements.opted_out.checked;fields.identity_conflict=form.elements.identity_conflict.checked;
  work('Saving customer changes and invalidating stale previews…',async()=>{await api('leads/'+encodeURIComponent(id),mutation(fields));$('#lead-dialog').close();await refresh();notice('Customer updated. Source changes are rechecked before approval and execution.');});
};
$('#close-source').onclick=()=>$('#lead-dialog').close();
const params=new URLSearchParams(location.search);
if(location.pathname==='/workspace'||params.get('page')==='dashboard'||activeId){
  $('#landing').hidden=true;showLogin();refresh().catch(error=>{$('#login-error').textContent=error.message;});
}
