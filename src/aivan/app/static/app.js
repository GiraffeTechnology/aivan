'use strict';

const state = {
  csrf: '',
  session: null,
  bootstrap: null,
  cases: [],
  offset: 0,
  limit: 20,
  total: 0,
  selectedCase: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const roleLabels = {
  admin: '管理员', sales: '销售', procurement: '采购', follow_up: '跟单',
  approver: '审批人', auditor: '审计员', qc: '质检', logistics: '物流',
  buyer: '买家', supplier: '供应商',
};
const stateLabels = {
  inquiry: '询盘', sourcing: '寻源', awaiting_supplier: '等待供应商',
  supplier_replied: '供应商已回复', awaiting_approval: '等待审批',
  approved: '已审批', qc: '质检', logistics: '物流', completed: '已完成',
  cancelled: '已取消',
};
const t = (source) => window.myAivanI18n?.t(source) || source;
const roleLabel = (role) => t(roleLabels[role] || role);
const stateLabel = (caseState) => t(stateLabels[caseState] || caseState);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
}

function cookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split('; ').find((entry) => entry.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : '';
}

function requestId(prefix = 'ui') {
  return `${prefix}-${crypto.randomUUID()}`;
}

function toast(message, kind = 'info') {
  const node = $('#toast');
  node.textContent = message;
  node.className = `toast ${kind}`;
  node.hidden = false;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { node.hidden = true; }, 4200);
}

const ht = (source) => escapeHtml(t(source));

async function loadUiCatalog(code) {
  return window.myAivanI18n?.ensureGeneratedCatalog(code) ?? false;
}

async function api(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    state.csrf = state.csrf || cookie('aivan_csrf');
    if (state.csrf) headers.set('X-AIVAN-CSRF', state.csrf);
    if (!headers.has('Idempotency-Key')) headers.set('Idempotency-Key', requestId('myaivan'));
  }
  const response = await fetch(path, { ...options, method, headers, credentials: 'same-origin' });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' ? payload.detail : payload;
    const message = typeof detail === 'string' ? detail : (detail?.error || `HTTP ${response.status}`);
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function showLogin(message = '') {
  $('#login-view').hidden = false;
  $('#app-shell').hidden = true;
  const error = $('#login-error');
  error.textContent = message;
  error.hidden = !message;
}

function showApp() {
  $('#login-view').hidden = true;
  $('#app-shell').hidden = false;
}

function setView(name) {
  window.myAivanAttachments?.dispose();
  $$('.view').forEach((node) => node.classList.toggle('active', node.id === `view-${name}`));
  $$('.nav-item').forEach((node) => node.classList.toggle('active', node.dataset.view === name));
  history.replaceState(null, '', `#${name}`);
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (name === 'cases') loadCases();
  if (name === 'relay') loadRelay();
  if (name === 'health') loadHealth();
}

function populateRoles(roles, selected) {
  const select = $('#role-select');
  select.replaceChildren(...roles.map((role) => {
    const option = document.createElement('option');
    option.value = role;
    option.textContent = roleLabel(role);
    option.selected = role === selected;
    return option;
  }));
}

async function establishSession() {
  state.csrf = cookie('aivan_csrf');
  try {
    const fragment = new URLSearchParams(location.hash.slice(1));
    const testTicket = fragment.get('test');
    if (testTicket) {
      history.replaceState(null, '', `${location.pathname}${location.search}#dashboard`);
      const response = await fetch('/api/session/test-login', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket: testTicket }),
      });
      const payload = await response.json();
      if (!response.ok) {
        const error = new Error(payload.detail?.error || t('测试账号不可用'));
        error.status = response.status;
        throw error;
      }
      state.csrf = payload.csrf_token;
    }
    state.session = await api('/api/session');
    showApp();
    $('#test-account-banner').hidden = !state.session.test_account;
    $$('.test-account-restricted').forEach((node) => {
      node.hidden = Boolean(state.session.test_account);
    });
    populateRoles(state.session.allowed_roles || [state.session.role], state.session.role);
    await loadBootstrap();
    await Promise.all([loadCases(true), loadHealth()]);
    const requestedView = location.hash.slice(1);
    const recoverableViews = ['welcome', 'dashboard', 'cases', 'new-inquiry', 'relay', 'health'];
    setView(recoverableViews.includes(requestedView) ? requestedView : 'welcome');
  } catch (error) {
    if (error.status === 401 || error.status === 403) showLogin();
    else showLogin(t('无法恢复会话，请重新登录。'));
  }
}

async function login(event) {
  event.preventDefault();
  const keyInput = $('#access-key');
  const button = event.submitter;
  button.disabled = true;
  try {
    const response = await fetch('/api/session/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-AIVAN-API-Key': keyInput.value },
      body: '{}',
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail?.error || t('登录失败'));
    state.csrf = payload.csrf_token;
    keyInput.value = '';
    state.session = payload;
    showApp();
    $('#test-account-banner').hidden = true;
    populateRoles(payload.allowed_roles, payload.role);
    await Promise.all([loadBootstrap(), loadCases(true), loadHealth()]);
    setView('welcome');
  } catch (error) {
    showLogin(error.message);
  } finally {
    keyInput.value = '';
    button.disabled = false;
  }
}

async function logout() {
  try { await api('/api/session/logout', { method: 'POST', body: '{}' }); } catch (_) { /* expire locally */ }
  state.csrf = '';
  state.session = null;
  showLogin();
}

async function switchRole(event) {
  const previous = state.session.role;
  try {
    const payload = await api('/api/session/role', {
      method: 'POST', body: JSON.stringify({ role: event.target.value }),
    });
    state.session = payload;
    state.csrf = payload.csrf_token;
    state.selectedCase = null;
    setView('dashboard');
    await Promise.all([loadBootstrap(), loadCases(true), loadHealth()]);
    toast(`${t('已切换为')}${roleLabel(payload.role)}`, 'success');
  } catch (error) {
    event.target.value = previous;
    toast(`${t('角色切换失败：')}${error.message}`, 'error');
  }
}

async function loadBootstrap() {
  state.bootstrap = await api('/api/workbench/bootstrap');
  await window.myAivanI18n?.assertCandidate(state.bootstrap.candidate_sha);
  const sha = state.bootstrap.candidate_sha;
  $('#candidate-banner').innerHTML = sha
    ? `<strong>${ht('冻结候选')}</strong><code>${escapeHtml(sha)}</code><span>API ${escapeHtml(state.bootstrap.api_version)}</span>`
    : `<strong>${ht('候选未冻结')}</strong><span>${ht('仅可作为非生产工作台使用。')}</span>`;
}

function caseCard(item) {
  const summary = item.requirement_summary || {};
  return `<article class="case-card" tabindex="0" data-case-id="${escapeHtml(item.case_id)}">
    <div class="case-main"><span class="status-pill state-${escapeHtml(item.case_state)}">${escapeHtml(stateLabel(item.case_state))}</span>
      <h3>${escapeHtml(summary.product_name || item.category || t('未命名询盘'))}</h3>
      <p>${escapeHtml(item.customer_display_name || item.customer_id || t('未知客户'))} · ${escapeHtml(item.channel || 'manual')}</p>
    </div>
    <div class="case-meta"><code>${escapeHtml(item.case_id)}</code><time>${escapeHtml(formatTime(item.updated_at))}</time></div>
  </article>`;
}

function formatTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  const locale = document.documentElement.lang || 'en';
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

async function loadCases(reset = false) {
  if (reset) state.offset = 0;
  const filter = $('#case-state-filter')?.value || '';
  const params = new URLSearchParams({ offset: state.offset, limit: state.limit });
  if (filter) params.set('state', filter);
  try {
    const payload = await api(`/api/workbench/cases?${params}`);
    state.cases = payload.items;
    state.total = payload.page.total;
    const html = payload.items.length ? payload.items.map(caseCard).join('') : emptyHtml();
    $('#case-list').innerHTML = html;
    $('#recent-cases').innerHTML = payload.items.slice(0, 5).map(caseCard).join('') || emptyHtml();
    $('#page-summary').textContent = `${state.offset + 1}-${Math.min(state.offset + payload.items.length, state.total)} / ${state.total}`;
    $('#prev-page').disabled = state.offset === 0;
    $('#next-page').disabled = !payload.page.has_more;
    renderMetrics(payload.items);
  } catch (error) {
    $('#case-list').innerHTML = `<p class="error">${ht('读取案例失败：')}${escapeHtml(error.message)}</p>`;
  }
}

function renderMetrics(items) {
  const pending = items.filter((item) => item.case_state === 'awaiting_approval').length;
  const active = items.filter((item) => !['completed', 'cancelled'].includes(item.case_state)).length;
  const cards = [
    [t('可见案例'), state.total, t('当前角色投影')], [t('活跃案例'), active, t('本页统计')],
    [t('等待审批'), pending, t('需要人工决定')], [t('当前角色'), roleLabel(state.session?.role), t('服务器授权')],
  ];
  $('#metric-grid').innerHTML = cards.map(([label, value, note]) => `<article class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`).join('');
}

function emptyHtml() {
  return `<div class="empty"><strong>${ht('暂无数据')}</strong><span>${ht('当前筛选条件下没有可显示的记录。')}</span></div>`;
}

function section(title, items, renderer) {
  return `<section class="detail-section"><div class="panel-heading"><h2>${escapeHtml(title)}</h2><span class="count">${items.length}</span></div>${items.length ? `<div class="timeline">${items.map(renderer).join('')}</div>` : emptyHtml()}</section>`;
}

function buyerOptionRow(option) {
  const quote = option.quote || {};
  const leadTime = option.lead_time_estimate || {};
  const supplier = option.supplier_display_name || option.supplier_id || option.candidate_id || 'Supplier pending confirmation';
  const warnings = Array.isArray(option.warnings) ? option.warnings : [];
  return `<article class="draft-card"><div><strong>${escapeHtml(option.option_label || option.option_type || 'Recommendation pending review')}</strong><span>${escapeHtml(supplier)}</span></div>
    <p>${escapeHtml(option.reasoning || 'No recommendation rationale is available.')}</p>
    <p>Price: ${escapeHtml(quote.currency || '')} ${escapeHtml(quote.buyer_unit_price ?? 'Unknown')} · Lead time: ${escapeHtml(leadTime.expected_days ?? 'Unknown')}</p>
    ${warnings.length ? `<p class="error">${escapeHtml(warnings.join(' · '))}</p>` : ''}</article>`;
}

function savedMessageRow(message) {
  const resolved = message.body_resolution === 'resolved'
    && message.canonical_language === 'en'
    && typeof message.message_text === 'string';
  let body = 'Message body unavailable: the returned content could not be verified.';
  if (resolved) body = message.message_text;
  else if (message.body_resolution === 'missing_legacy_content') {
    body = 'Message body unavailable: this legacy record contains no recoverable body.';
  } else if (message.body_resolution === 'integrity_mismatch') {
    body = 'Message body unavailable: the integrity check failed.';
  }
  return `<article><strong>${escapeHtml(roleLabel(message.actor_role))}</strong><p class="saved-message-body"${resolved ? ' lang="en"' : ''}>${escapeHtml(body)}</p><time>${escapeHtml(formatTime(message.created_at))}</time></article>`;
}

async function openCase(caseId) {
  setView('case-detail');
  $('#case-detail').innerHTML = `<div class="loading-card">${ht('正在读取共享 Core 数据…')}</div>`;
  try {
    const payload = await api(`/api/workbench/cases/${encodeURIComponent(caseId)}`);
    state.selectedCase = payload;
    const item = payload.case;
    const canExport = state.bootstrap.actor.capabilities.includes('view_audit');
    const selected = item.selected_option;
    const buyerOptions = Array.isArray(item.requirement?.buyer_options) ? item.requirement.buyer_options : [];
    const orderConfirmation = item.requirement?.order_confirmation;
    const canConfirmOrder = state.bootstrap.actor.capabilities.includes('approve_outbound')
      && item.case_state === 'approved'
      && selected?.option_id
      && orderConfirmation?.status !== 'confirmed';
    const recommendation = selected ? `<section class="panel"><h2>Execution recommendation</h2>
      <div class="person"><strong>${escapeHtml(selected.option_label || selected.option_type || 'Recommendation pending review')}</strong><span>${escapeHtml(selected.supplier_display_name || selected.supplier_id || selected.candidate_id || 'Supplier pending confirmation')}</span></div>
      <p>${escapeHtml(selected.reasoning || 'No recommendation rationale is available.')}</p>
      <p>Price: ${escapeHtml(selected.quote?.currency || '')} ${escapeHtml(selected.quote?.buyer_unit_price ?? 'Unknown')} · Lead time: ${escapeHtml(selected.lead_time_estimate?.expected_days ?? 'Unknown')}</p>
      ${(selected.warnings || []).length ? `<p class="error">${escapeHtml(selected.warnings.join(' · '))}</p>` : ''}
      ${canConfirmOrder ? `<button class="primary" data-action="confirm-order" data-case-id="${escapeHtml(item.case_id)}" data-option-id="${escapeHtml(selected.option_id)}" type="button">${ht('确认选定订单')}</button>` : ''}</section>` : '';
    const confirmedOrder = orderConfirmation?.status === 'confirmed'
      ? `<section class="panel"><h2>${ht('订单确认')}</h2><div class="person"><strong>${ht('已由人工确认')}</strong><span>${escapeHtml(orderConfirmation.purchase_order_id || '')}</span></div><p>${ht('权威数据库回读已验证')} · ${escapeHtml(orderConfirmation.authoritative_source || 'giraffe-db')}</p></section>`
      : '';
    $('#case-detail').innerHTML = `<section class="case-hero">
      <div><p class="eyebrow">${escapeHtml(item.case_id)}</p><h1 id="case-detail-title">${escapeHtml(item.requirement?.product_name || item.category || t('业务案例'))}</h1><p>${escapeHtml(item.customer_display_name || item.customer_id)}</p></div>
      <div class="hero-actions"><span class="status-pill state-${escapeHtml(item.case_state)}">${escapeHtml(stateLabel(item.case_state))}</span>${canExport ? `<a class="secondary button" href="/api/workbench/cases/${encodeURIComponent(item.case_id)}/export?format=markdown">${ht('导出审计')}</a>` : ''}</div>
    </section>
    ${section('Saved conversation', payload.messages, savedMessageRow)}
    <section class="panel" id="case-attachments"></section>
    <div class="detail-grid"><section class="panel"><h2>${ht('需求事实')}</h2><pre class="json-view">${escapeHtml(JSON.stringify(item.requirement || {}, null, 2))}</pre></section>
    <section class="panel"><h2>${ht('参与者与角色')}</h2>${payload.participants.length ? payload.participants.map((p) => `<div class="person"><strong>${escapeHtml(p.display_name || p.actor_id)}</strong><span>${escapeHtml(roleLabel(p.business_role))} · ${escapeHtml(p.conversation_role)}</span></div>`).join('') : emptyHtml()}</section></div>
    ${recommendation}
    ${confirmedOrder}
    ${section('Quote options', buyerOptions, buyerOptionRow)}
    ${section(t('待办与草稿'), payload.drafts, draftRow)}
    ${section(t('审批'), payload.approvals, (a) => `<article><strong>${escapeHtml(a.status)}</strong><span>${escapeHtml(a.approver_id || t('待审批'))}</span><time>${escapeHtml(formatTime(a.decided_at || a.created_at))}</time></article>`)}
    ${section(t('回执'), payload.receipts, (r) => `<article><strong>${escapeHtml(r.channel)} · ${escapeHtml(r.receipt_id)}</strong><span>${escapeHtml(r.receipt_reference || r.external_message_id || t('摘要回执'))}</span><time>${escapeHtml(formatTime(r.confirmed_at))}</time></article>`)}
    ${section(t('事件时间线'), payload.events, eventRow)}
    ${section(t('审计记录'), payload.audit, (a) => `<article><strong>${escapeHtml(a.event_type)}</strong><span>${escapeHtml(a.actor_role)} · ${escapeHtml(a.actor_id)}</span><code>${escapeHtml(a.source_trace_id)}</code><time>${escapeHtml(formatTime(a.created_at))}</time></article>`)}`;
    window.myAivanAttachments?.mount($('#case-attachments'), item.case_id, api);
  } catch (error) {
    $('#case-detail').innerHTML = `<p class="error">${ht('读取案例失败：')}${escapeHtml(error.message)}</p>`;
  }
}

function draftRow(draft) {
  const canApprove = state.bootstrap.actor.capabilities.includes('approve_outbound');
  const actions = draft.status === 'pending_approval' && canApprove
    ? `<button class="secondary compact" data-action="reject" data-draft-id="${escapeHtml(draft.draft_id)}" type="button">${ht('拒绝')}</button><button class="primary compact" data-action="approve" data-draft-id="${escapeHtml(draft.draft_id)}" type="button">${ht('审批')}</button>` : '';
  return `<article class="draft-card"><div><strong>${escapeHtml(draft.target_role)} · ${escapeHtml(draft.channel)}</strong><span class="status-pill">${escapeHtml(draft.status)}</span></div><p>${escapeHtml(draft.message_text)}</p><div class="row-actions"><button class="ghost compact" data-action="copy" data-copy="${escapeHtml(draft.message_text)}" data-copy-case-id="${escapeHtml(draft.case_id)}" data-draft-id="${escapeHtml(draft.draft_id)}" data-content-sha256="${escapeHtml(draft.content_sha256)}" type="button">${ht('复制')}</button>${actions}</div></article>`;
}

function eventRow(event) {
  const canReverse = state.bootstrap.actor.capabilities.includes('reverse_event');
  return `<article><strong>${escapeHtml(event.event_type)}</strong><span>${escapeHtml(event.summary)}</span><time>${escapeHtml(formatTime(event.created_at))}</time>${canReverse ? `<span class="row-actions"><button class="ghost compact" data-action="impact" data-event-id="${escapeHtml(event.event_id)}" type="button">${ht('影响预览')}</button><button class="secondary compact" data-action="reverse" data-event-id="${escapeHtml(event.event_id)}" type="button">${ht('纠错')}</button></span>` : ''}</article>`;
}

async function showInquiryConversation(caseId, input, response) {
  const stream = $('#conversation-stream');
  const review = $('#outbound-review-content');
  stream.replaceChildren();
  for (const [className, text] of [['user-message', input], ['assistant-message', response]]) {
    const message = document.createElement('p');
    message.className = `conversation-message ${className}`;
    message.textContent = text;
    stream.append(message);
  }
  review.textContent = 'Loading saved drafts…';
  try {
    const detail = await api(`/api/workbench/cases/${encodeURIComponent(caseId)}`);
    if (!Array.isArray(detail.drafts)) throw new Error('Invalid draft response');
    if (detail.drafts.length) review.innerHTML = detail.drafts.map(draftRow).join('');
    else review.textContent = 'No saved draft is available yet. Open the case for clarification or status.';
  } catch (_) {
    review.textContent = 'The input was accepted, but saved drafts could not be loaded. Reopen the case to retry. No message was sent by this view.';
  }
}

function inquirySubmissionOutcome(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  if (payload.status !== 'ok' || typeof payload.project_id !== 'string') return null;
  const projectId = payload.project_id.trim();
  if (!projectId) return null;
  const draftsCreated = payload.drafts_created;
  const enteredApprovalFlow = payload.action === 'pending_email_approval'
    && Array.isArray(draftsCreated)
    && draftsCreated.length > 0
    && draftsCreated.every((draftId) => typeof draftId === 'string' && draftId.trim());
  return {
    projectId,
    enteredApprovalFlow,
  };
}

async function submitInquiry(event) {
  event.preventDefault();
  const buyerId = $('#buyer-id').value.trim();
  const text = $('#inquiry-text').value.trim();
  const conversation = requestId('manual-conversation');
  const result = $('#inquiry-result');
  result.hidden = true;
  result.textContent = '';
  const headers = {
    'X-AIVAN-Participant-ID': buyerId,
    'X-AIVAN-Participant-Role': 'buyer',
    'X-AIVAN-Participant-Conversation-Role': 'buyer_thread',
  };
  try {
    const payload = await api('/invoke', {
      method: 'POST', headers,
      body: JSON.stringify({
        source: 'myaivan', channel: 'myaivan', conversation_id: conversation,
        message_id: requestId('manual-message'), sender_id: buyerId,
        sender_display_name: $('#buyer-name').value.trim(), message_text: text,
      }),
    });
    const outcome = inquirySubmissionOutcome(payload);
    if (!outcome) throw new Error(t('服务器未确认案例创建，请检查输入后重试。'));
    result.hidden = false;
    const responseMessage = payload.action === 'pending_email_approval' && !outcome.enteredApprovalFlow
      ? t('请求已受理，请按案例提示继续。')
      : (payload.user_control_message || payload.message || payload.reply_text || t('请求已受理，请按案例提示继续。'));
    result.textContent = `${t('案例')} ${outcome.projectId}\n${responseMessage}`;
    await loadCases(true);
    if ($('#conversation-stream')) await showInquiryConversation(outcome.projectId, text, responseMessage);
    if (outcome.enteredApprovalFlow) {
      event.target.reset();
      toast(t('询盘草稿已生成，等待人工审批'), 'success');
    } else {
      toast(t('请求已受理，请按案例提示继续。'), 'info');
    }
  } catch (error) {
    toast(`${t('创建失败：')}${error.message}`, 'error');
  }
}

async function approveDraft(draftId) {
  try {
    const payload = await api(`/api/drafts/${encodeURIComponent(draftId)}/approve`, { method: 'POST', body: '{}' });
    toast(payload.relay_required ? t('已审批，等待人工转发') : (payload.sent ? t('已审批并产生发送回执') : t('审批完成')), 'success');
    if (state.selectedCase) await openCase(state.selectedCase.case.case_id);
  } catch (error) { toast(`${t('审批失败：')}${error.message}`, 'error'); }
}

async function rejectDraft(draftId) {
  if (!window.confirm(t('确认拒绝当前草稿并返回修订？'))) return;
  try {
    await api(`/api/drafts/${encodeURIComponent(draftId)}/reject`, { method: 'POST', body: '{}' });
    toast(t('已拒绝，案例可继续修订'), 'success');
    if (state.selectedCase) await openCase(state.selectedCase.case.case_id);
  } catch (error) { toast(`${t('拒绝失败：')}${error.message}`, 'error'); }
}

async function confirmOrder(caseId, optionId) {
  if (!window.confirm(t('确认将当前选定报价写入订单？此操作需要人工授权。'))) return;
  try {
    const payload = await api(`/api/workbench/cases/${encodeURIComponent(caseId)}/order-confirmation`, {
      method: 'POST',
      body: JSON.stringify({ selected_option_id: optionId }),
    });
    toast(payload.recovered ? t('订单已恢复并通过数据库回读') : t('订单已确认并通过数据库回读'), 'success');
    await openCase(caseId);
  } catch (error) {
    toast(`${t('订单确认失败：')}${error.message}`, 'error');
  }
}

async function copyDraftText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied to clipboard. This does not send the draft.', 'success');
    return true;
  } catch (_) {
    const field = $('#manual-copy-text');
    field.value = text;
    $('#manual-copy-dialog').showModal();
    field.focus();
    field.select();
    toast('Automatic copy was unavailable. Use Ctrl+C or Cmd+C on the selected text.', 'info');
    return false;
  }
}

async function copyAndRecordDraft(button) {
  if (button.disabled) return;
  button.disabled = true;
  let clipboardCompleted = false;
  try {
    const text = button.dataset.copy || '';
    if (!await copyDraftText(text)) return;
    clipboardCompleted = true;
    const { copyCaseId, draftId, contentSha256 } = button.dataset;
    if (!copyCaseId || !draftId || !/^[a-f0-9]{64}$/.test(contentSha256 || '')) {
      throw new Error('Copy audit identity unavailable');
    }
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    const actual = Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, '0')).join('');
    if (actual !== contentSha256) throw new Error('Copy content changed');
    button.dataset.copyKey ||= requestId('copy');
    const result = await api(`/api/workbench/cases/${encodeURIComponent(copyCaseId)}/drafts/${encodeURIComponent(draftId)}/copy`, {
      method: 'POST',
      headers: { 'Idempotency-Key': button.dataset.copyKey },
      body: JSON.stringify({ content_sha256: contentSha256 }),
    });
    if (result.status !== 'copied' || result.delivery_claim !== false || !result.audit_id) {
      throw new Error('Copy audit not confirmed');
    }
    delete button.dataset.copyKey;
    toast('Copied and recorded. No message was sent.', 'success');
  } catch (_) {
    toast(clipboardCompleted
      ? 'Copied to clipboard, but the copy audit was not confirmed. Retry or reopen the case. No delivery is claimed.'
      : 'Copy could not be confirmed. Select the draft text and copy it manually. No delivery is claimed.', 'info');
  } finally {
    button.disabled = false;
  }
}

async function showImpact(eventId) {
  try {
    const payload = await api(`/api/events/${encodeURIComponent(eventId)}/impact`);
    toast(`${t('影响范围：')}${JSON.stringify(payload).slice(0, 220)}`, 'info');
  } catch (error) { toast(`${t('预览失败：')}${error.message}`, 'error'); }
}

async function reverseEvent(eventId) {
  const reason = window.prompt(t('请输入纠错原因。操作将写入不可变审计记录；不物理删除历史。'));
  if (!reason?.trim()) return;
  try {
    const payload = await api(`/api/events/${encodeURIComponent(eventId)}/reverse`, {
      method: 'POST', body: JSON.stringify({ reason: reason.trim() }),
    });
    toast(payload.status === 'applied' ? t('纠错已应用') : t('已创建补偿任务'), 'success');
    if (state.selectedCase) await openCase(state.selectedCase.case.case_id);
  } catch (error) { toast(`${t('纠错失败：')}${error.message}`, 'error'); }
}

async function loadRelay() {
  const list = $('#relay-list');
  list.innerHTML = `<div class="loading-card">${ht('正在读取转发队列…')}</div>`;
  try {
    const payload = await api('/api/relay/outbox');
    list.innerHTML = payload.outbox.length ? payload.outbox.map((item) => `<article class="relay-card">
      <div><span class="status-pill">${escapeHtml(item.channel)}</span><code>${escapeHtml(item.draft_id)}</code></div>
      <p>${escapeHtml(item.message_text)}</p>
      <button class="secondary" data-action="copy" data-copy="${escapeHtml(item.message_text)}" data-copy-case-id="${escapeHtml(item.project_id)}" data-draft-id="${escapeHtml(item.draft_id)}" data-content-sha256="${escapeHtml(item.content_sha256)}" type="button">${ht('复制内容')}</button>
      <form class="relay-confirm" data-draft-id="${escapeHtml(item.draft_id)}"><label>${ht('发送后的回执编号')}<input name="receipt" required placeholder="${ht('外部消息 ID 或人工回执编号')}"></label><button class="primary" type="submit">${ht('确认已人工转发')}</button></form>
    </article>`).join('') : emptyHtml();
  } catch (error) { list.innerHTML = `<p class="error">${ht('读取转发队列失败：')}${escapeHtml(error.message)}</p>`; }
}

async function confirmRelay(event) {
  event.preventDefault();
  const draftId = event.target.dataset.draftId;
  const receipt = new FormData(event.target).get('receipt').trim();
  try {
    await api(`/api/relay/${encodeURIComponent(draftId)}/confirm`, {
      method: 'POST', body: JSON.stringify({ receipt_reference: receipt, metadata: { source: 'myaivan_mobile' } }),
    });
    toast(t('已记录 relayed 回执'), 'success');
    await loadRelay();
  } catch (error) { toast(`${t('确认失败：')}${error.message}`, 'error'); }
}

async function loadHealth() {
  try {
    const health = await api('/api/workbench/health');
    const entries = [
      [t('数据库'), health.database.configured, t('运行时配置')],
      ['GPM', !health.gpm.durable_required || health.gpm.backend !== 'memory', health.gpm.backend],
      ['OpenClaw', health.openclaw.configured, t('只读配置检查')],
      [t('本地模型'), health.model.configured, t('只读配置检查')],
      [t('候选版本'), Boolean(health.candidate_sha), health.candidate_sha || t('未冻结')],
    ];
    $('#health-grid').innerHTML = entries.map(([label, ok, note]) => `<article class="health-card ${ok ? 'ok' : 'pending'}"><span class="health-dot" aria-hidden="true"></span><div><strong>${escapeHtml(label)}</strong><p>${escapeHtml(note)}</p></div><span>${ok ? ht('已配置') : ht('待完成')}</span></article>`).join('');
  } catch (error) { $('#health-grid').innerHTML = `<p class="error">${ht('读取健康状态失败：')}${escapeHtml(error.message)}</p>`; }
}

document.addEventListener('click', async (event) => {
  const open = event.target.closest('[data-open-view]');
  if (open) return setView(open.dataset.openView);
  const nav = event.target.closest('[data-view]');
  if (nav) return setView(nav.dataset.view);
  const card = event.target.closest('[data-case-id]');
  if (card) return openCase(card.dataset.caseId);
  const action = event.target.closest('[data-action]');
  if (!action) return;
  if (action.dataset.action === 'copy') {
    await copyAndRecordDraft(action);
  }
  if (action.dataset.action === 'approve') await approveDraft(action.dataset.draftId);
  if (action.dataset.action === 'reject') await rejectDraft(action.dataset.draftId);
  if (action.dataset.action === 'confirm-order') await confirmOrder(action.dataset.caseId, action.dataset.optionId);
  if (action.dataset.action === 'impact') await showImpact(action.dataset.eventId);
  if (action.dataset.action === 'reverse') await reverseEvent(action.dataset.eventId);
});

document.addEventListener('keydown', (event) => {
  const card = event.target.closest?.('[data-case-id]');
  if (card && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); openCase(card.dataset.caseId); }
});

document.addEventListener('submit', (event) => {
  if (event.target.id === 'login-form') login(event);
  if (event.target.id === 'inquiry-form') submitInquiry(event);
  if (event.target.matches('.relay-confirm')) confirmRelay(event);
});

$('#logout-button').addEventListener('click', logout);
$('#paste-inquiry')?.addEventListener('click', async () => {
  const field = $('#inquiry-text');
  try {
    field.value += await navigator.clipboard.readText();
    $('#input-status').textContent = 'Pasted into the input. Review before sending to Aivan.';
  } catch (_) {
    $('#input-status').textContent = 'Clipboard access is unavailable. Use Ctrl+V or Cmd+V in the input.';
  }
  field.focus();
});
$('#role-select').addEventListener('change', switchRole);
$('#case-state-filter').addEventListener('change', () => loadCases(true));
$('#refresh-cases').addEventListener('click', () => loadCases());
$('#prev-page').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); loadCases(); });
$('#next-page').addEventListener('click', () => { state.offset += state.limit; loadCases(); });

window.addEventListener('myaivan:locale', async () => {
  const selectedLocale = window.myAivanI18n?.locale || 'zh';
  await loadUiCatalog(selectedLocale);
  if (!state.session || selectedLocale !== window.myAivanI18n?.locale) return;
  populateRoles(state.session.allowed_roles || [state.session.role], state.session.role);
  await Promise.all([loadBootstrap(), loadCases(), loadHealth()]);
  if (state.selectedCase && $('#view-case-detail').classList.contains('active')) {
    await openCase(state.selectedCase.case.case_id);
  }
});

establishSession();
