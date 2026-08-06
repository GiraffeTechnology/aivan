// AIVAN Frontend Application

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[ch]);
}

function encoded(value) {
    return encodeURIComponent(String(value ?? ''));
}

function statusClass(value) {
    return /^[a-z0-9_-]+$/i.test(String(value ?? '')) ? String(value) : 'unknown';
}

const connectionFields = {
    'cfg-api-key': 'apiKey',
    'cfg-tenant-id': 'tenantId',
    'cfg-actor-id': 'actorId',
    'cfg-role-context': 'roleContext',
    'cfg-conversation-role': 'conversationRole',
    'cfg-execution-mode': 'executionMode',
    'cfg-channel-account-id': 'channelAccountId',
};

function loadConnectionSettings() {
    Object.entries(connectionFields).forEach(([elementId, key]) => {
        const element = document.getElementById(elementId);
        if (element) element.value = sessionStorage.getItem('aivan.' + key) || '';
    });
}

function saveConnectionSettings() {
    Object.entries(connectionFields).forEach(([elementId, key]) => {
        const value = document.getElementById(elementId)?.value.trim() || '';
        if (value) sessionStorage.setItem('aivan.' + key, value);
        else sessionStorage.removeItem('aivan.' + key);
    });
    document.getElementById('settings-result').textContent = 'Connection settings saved for this browser tab.';
}

function clearConnectionSettings() {
    Object.values(connectionFields).forEach(key => sessionStorage.removeItem('aivan.' + key));
    loadConnectionSettings();
    document.getElementById('settings-result').textContent = 'Connection settings cleared.';
}

function requestHeaders() {
    const mapping = {
        apiKey: 'X-AIVAN-API-Key', tenantId: 'X-AIVAN-Tenant-ID',
        actorId: 'X-AIVAN-Actor-ID', roleContext: 'X-AIVAN-Role-Context',
        conversationRole: 'X-AIVAN-Conversation-Role', executionMode: 'X-AIVAN-Execution-Mode',
        channelAccountId: 'X-AIVAN-Channel-Account-ID',
    };
    const headers = { 'Content-Type': 'application/json' };
    Object.entries(mapping).forEach(([key, header]) => {
        const value = sessionStorage.getItem('aivan.' + key);
        if (value) headers[header] = value;
    });
    return headers;
}

function showPanel(name) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById('panel-' + name);
    if (panel) panel.classList.add('active');
    if (name === 'projects') loadProjects();
    if (name === 'suppliers') loadSuppliers();
    if (name === 'platforms') { loadPlatforms(); loadSuggestions(); }
    if (name === 'accounts') loadAccounts();
}

async function apiFetch(url, options = {}) {
    const res = await fetch(url, {
        ...options,
        headers: { ...requestHeaders(), ...(options.headers || {}) },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    return res.json();
}

async function sendMessage() {
    const text = document.getElementById('msg-text').value.trim();
    const conv = document.getElementById('msg-conv').value.trim();
    const sender = document.getElementById('msg-sender').value.trim();
    const resultBox = document.getElementById('message-result');
    if (!text || !conv || !sender) {
        resultBox.textContent = 'Message, conversation ID, and sender ID are required.';
        return;
    }
    resultBox.textContent = 'Sending...';
    try {
        const data = await apiFetch('/api/openclaw/events', {
            method: 'POST',
            body: JSON.stringify({
                source: 'openclaw',
                channel: 'openclaw-weixin',
                channel_account_id: sessionStorage.getItem('aivan.channelAccountId') || '',
                conversation_id: conv,
                message_id: 'msg_' + Date.now(),
                sender_id: sender,
                sender_display_name: sender,
                message_text: text,
                message_type: 'text',
                attachments: [],
                timestamp: new Date().toISOString(),
                mode: 'manual',
            }),
        });
        resultBox.textContent = JSON.stringify(data, null, 2);
    } catch (e) {
        resultBox.textContent = 'Error: ' + e.message;
    }
}

async function loadProjects() {
    const list = document.getElementById('projects-list');
    try {
        const data = await apiFetch('/api/projects');
        if (!data.projects.length) {
            list.innerHTML = '<p style="color:#888">No projects yet. Send a message to create one.</p>';
            return;
        }
        list.innerHTML = data.projects.map(p => `
            <div class="card">
                <h3>${escapeHtml(p.project_id)}</h3>
                <p>Status: <span class="tag">${escapeHtml(p.status)}</span></p>
                <p>Category: ${escapeHtml(p.category || 'unknown')}</p>
                <p>Customer: ${escapeHtml(p.customer_id)}</p>
                <p>Created: ${escapeHtml(p.created_at)}</p>
                <button onclick="loadProjectEvents(decodeURIComponent('${encoded(p.project_id)}'))">View Events</button>
                <div id="events-${encoded(p.project_id)}" style="margin-top:1rem;font-size:0.8rem;color:#555;display:none;"></div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + escapeHtml(e.message) + '</p>';
    }
}

async function loadProjectEvents(projectId) {
    const el = document.getElementById('events-' + encoded(projectId));
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
    if (el.style.display === 'none') return;
    try {
        const data = await apiFetch('/api/projects/' + encoded(projectId) + '/events');
        el.innerHTML = data.events.map(e =>
            `<div style="padding:4px 0;border-top:1px solid #eee">[${escapeHtml(e.event_type)}] ${escapeHtml(e.summary)}</div>`
        ).join('') || '<p>No events yet</p>';
    } catch (e) {
        el.textContent = 'Error: ' + e.message;
    }
}

async function loadSuppliers() {
    const list = document.getElementById('suppliers-list');
    try {
        const data = await apiFetch('/api/suppliers');
        if (!data.suppliers.length) {
            list.innerHTML = '<p style="color:#888">No suppliers loaded. Run: uv run aivan import-suppliers data/sample_suppliers.csv</p>';
            return;
        }
        list.innerHTML = data.suppliers.map(s => `
            <div class="card">
                <h3>${escapeHtml(s.name)}</h3>
                <p>Type: <span class="tag">${escapeHtml(s.company_type)}</span></p>
                <p>Categories: ${(s.categories || []).map(c => '<span class="tag blue">'+escapeHtml(c)+'</span>').join('')}</p>
                <p>MOQ: ${escapeHtml(s.moq_min)} – ${escapeHtml(s.moq_max)} | Daily capacity: ${escapeHtml(s.daily_capacity)}</p>
                <p>Region: ${escapeHtml(s.region)}, ${escapeHtml(s.country)}</p>
                <p>Quality: ${escapeHtml((Number(s.quality_score || 0)*100).toFixed(0))}% | Delivery: ${escapeHtml((Number(s.delivery_score || 0)*100).toFixed(0))}%</p>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + escapeHtml(e.message) + '</p>';
    }
}

async function loadPlatforms() {
    const list = document.getElementById('platforms-list');
    try {
        const data = await apiFetch('/api/platforms');
        list.innerHTML = data.platforms.map(p => `
            <div class="card platform-${statusClass(p.status)}">
                <h3>${escapeHtml(p.display_name)} ${p.built_in ? '<span class="tag green">Built-in</span>' : ''}</h3>
                <p>Status: <span class="tag">${escapeHtml(p.status)}</span></p>
                <p>Domains: ${escapeHtml((p.domain_patterns || []).join(', '))}</p>
                <p>Search: ${p.allow_marketplace_search ? '✓' : '✗'} | Account mgmt: ${p.allow_openclaw_account_management ? '✓' : '✗'}</p>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + escapeHtml(e.message) + '</p>';
    }
}

async function loadSuggestions() {
    const list = document.getElementById('suggestions-list');
    try {
        const data = await apiFetch('/api/platforms/suggestions');
        if (!data.suggestions.length) {
            list.innerHTML = '<p style="color:#888">No pending platform suggestions.</p>';
            return;
        }
        list.innerHTML = data.suggestions.map(s => `
            <div class="card platform-pending">
                <h3>${escapeHtml(s.display_name)}</h3>
                <p>Domain: ${escapeHtml(s.domain)}</p>
                <p>Reason: ${escapeHtml(s.reason)}</p>
                <button class="approve" onclick="approveS(decodeURIComponent('${encoded(s.suggestion_id)}'))">Approve</button>
                <button class="reject" onclick="rejectS(decodeURIComponent('${encoded(s.suggestion_id)}'))">Reject</button>
                <button onclick="blockS(decodeURIComponent('${encoded(s.suggestion_id)}'))">Block</button>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + escapeHtml(e.message) + '</p>';
    }
}

async function approveS(id) { await apiFetch('/api/platforms/suggestions/'+encoded(id)+'/approve',{method:'POST'}); loadSuggestions(); loadPlatforms(); }
async function rejectS(id) { await apiFetch('/api/platforms/suggestions/'+encoded(id)+'/reject',{method:'POST'}); loadSuggestions(); }
async function blockS(id) { await apiFetch('/api/platforms/suggestions/'+encoded(id)+'/block',{method:'POST'}); loadSuggestions(); }

async function loadAccounts() {
    const list = document.getElementById('accounts-list');
    try {
        const data = await apiFetch('/api/openclaw/accounts');
        if (!data.accounts.length) {
            list.innerHTML = '<p style="color:#888">No OpenClaw accounts registered. AIVAN does not store platform credentials — accounts are managed by OpenClaw.</p>';
            return;
        }
        list.innerHTML = data.accounts.map(a => `
            <div class="card">
                <h3>${escapeHtml(a.display_name || a.account_connection_id)}</h3>
                <p>Platform: <span class="tag blue">${escapeHtml(a.platform)}</span></p>
                <p>Status: <span class="tag ${a.status==='connected'?'green':a.status==='revoked'?'red':'yellow'}">${escapeHtml(a.status)}</span></p>
                <p>Permissions: ${escapeHtml((a.permissions || []).join(', '))}</p>
                <button onclick="revokeAccount(decodeURIComponent('${encoded(a.account_connection_id)}'))">Revoke</button>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + escapeHtml(e.message) + '</p>';
    }
}

async function registerDemoAccount() {
    try {
        const data = await apiFetch('/api/openclaw/accounts/register', {
            method: 'POST',
            body: JSON.stringify({
                account_connection_id: 'oc_acc_1688_demo',
                platform: '1688',
                channel: 'openclaw-1688-im',
                channel_account_id: 'demo_1688_account',
                display_name: 'Demo 1688 Account',
                status: 'connected',
                permissions: ['read_messages', 'send_approved_messages', 'read_marketplace_search_results', 'open_seller_chat'],
                allowed_actions: ['search_suppliers', 'send_approved_message'],
            }),
        });
        alert('Account registered: ' + data.account_connection_id);
        loadAccounts();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function revokeAccount(id) {
    if (!confirm('Revoke account ' + id + '?')) return;
    await apiFetch('/api/openclaw/accounts/'+encoded(id)+'/revoke', {method:'POST'});
    loadAccounts();
}

async function loadDrafts() {
    const projectId = document.getElementById('approval-project-id').value.trim();
    if (!projectId) { alert('Enter a Project ID'); return; }
    const list = document.getElementById('drafts-list');
    try {
        const data = await apiFetch('/api/openclaw/projects/'+projectId+'/pending-drafts');
        if (!data.drafts.length) {
            list.innerHTML = '<p style="color:#888">No pending drafts for this project.</p>';
            return;
        }
        list.innerHTML = data.drafts.map(d => `
            <div class="card">
                <h3>Draft: ${escapeHtml(d.draft_id)}</h3>
                <p>To: ${escapeHtml(d.target_role)}</p>
                <p>Created by: ${escapeHtml(d.created_by_agent)}</p>
                <pre style="background:#f8f9fa;padding:8px;border-radius:4px;font-size:0.8rem;white-space:pre-wrap;margin:8px 0">${escapeHtml(d.message_text)}</pre>
                <button class="approve" onclick="approveDraft(decodeURIComponent('${encoded(d.draft_id)}'))">✓ Approve</button>
                <button class="reject" onclick="rejectDraft(decodeURIComponent('${encoded(d.draft_id)}'))">✗ Reject</button>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + escapeHtml(e.message) + '</p>';
    }
}

async function approveDraft(draftId) {
    try {
        const data = await apiFetch('/api/openclaw/drafts/'+encoded(draftId)+'/approve', {method:'POST', body: JSON.stringify({approved_by:'user'})});
        alert(data.sent ? 'Approved and sent.' : (data.relay_required ? 'Approved; guided relay is required.' : 'Approved; delivery remains pending.'));
        const projectId = document.getElementById('approval-project-id').value.trim();
        if (projectId) loadDrafts();
    } catch (e) { alert('Error: ' + e.message); }
}

async function rejectDraft(draftId) {
    try {
        await apiFetch('/api/openclaw/drafts/'+encoded(draftId)+'/reject', {method:'POST'});
        alert('Draft rejected');
        const projectId = document.getElementById('approval-project-id').value.trim();
        if (projectId) loadDrafts();
    } catch (e) { alert('Error: ' + e.message); }
}

// Load initial state
window.onload = () => { loadConnectionSettings(); loadProjects(); };
