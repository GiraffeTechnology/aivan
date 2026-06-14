// AIVEN Frontend Application

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
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    return res.json();
}

async function sendMessage() {
    const text = document.getElementById('msg-text').value.trim();
    const conv = document.getElementById('msg-conv').value.trim();
    const sender = document.getElementById('msg-sender').value.trim();
    if (!text) return;
    const resultBox = document.getElementById('message-result');
    resultBox.textContent = 'Sending...';
    try {
        const data = await apiFetch('/api/openclaw/events', {
            method: 'POST',
            body: JSON.stringify({
                source: 'openclaw',
                channel: 'openclaw-weixin',
                channel_account_id: 'salesperson-main',
                conversation_id: conv || 'conv_demo_001',
                message_id: 'msg_' + Date.now(),
                sender_id: sender || 'customer_001',
                sender_display_name: sender || 'Customer',
                message_text: text,
                message_type: 'text',
                attachments: [],
                timestamp: new Date().toISOString(),
                mode: 'auto',
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
                <h3>${p.project_id}</h3>
                <p>Status: <span class="tag">${p.status}</span></p>
                <p>Category: ${p.category || 'unknown'}</p>
                <p>Customer: ${p.customer_id}</p>
                <p>Created: ${p.created_at}</p>
                <button onclick="loadProjectEvents('${p.project_id}')">View Events</button>
                <div id="events-${p.project_id}" style="margin-top:1rem;font-size:0.8rem;color:#555;display:none;"></div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + e.message + '</p>';
    }
}

async function loadProjectEvents(projectId) {
    const el = document.getElementById('events-' + projectId);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
    if (el.style.display === 'none') return;
    try {
        const data = await apiFetch('/api/projects/' + projectId + '/events');
        el.innerHTML = data.events.map(e =>
            `<div style="padding:4px 0;border-top:1px solid #eee">[${e.event_type}] ${e.summary}</div>`
        ).join('') || '<p>No events yet</p>';
    } catch (e) {
        el.innerHTML = 'Error: ' + e.message;
    }
}

async function loadSuppliers() {
    const list = document.getElementById('suppliers-list');
    try {
        const data = await apiFetch('/api/suppliers');
        if (!data.suppliers.length) {
            list.innerHTML = '<p style="color:#888">No suppliers loaded. Run: uv run aiven import-suppliers data/sample_suppliers.csv</p>';
            return;
        }
        list.innerHTML = data.suppliers.map(s => `
            <div class="card">
                <h3>${s.name}</h3>
                <p>Type: <span class="tag">${s.company_type}</span></p>
                <p>Categories: ${s.categories.map(c => '<span class="tag blue">'+c+'</span>').join('')}</p>
                <p>MOQ: ${s.moq_min} – ${s.moq_max} | Daily capacity: ${s.daily_capacity}</p>
                <p>Region: ${s.region}, ${s.country}</p>
                <p>Quality: ${(s.quality_score*100).toFixed(0)}% | Delivery: ${(s.delivery_score*100).toFixed(0)}%</p>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + e.message + '</p>';
    }
}

async function loadPlatforms() {
    const list = document.getElementById('platforms-list');
    try {
        const data = await apiFetch('/api/platforms');
        list.innerHTML = data.platforms.map(p => `
            <div class="card platform-${p.status}">
                <h3>${p.display_name} ${p.built_in ? '<span class="tag green">Built-in</span>' : ''}</h3>
                <p>Status: <span class="tag">${p.status}</span></p>
                <p>Domains: ${p.domain_patterns.join(', ')}</p>
                <p>Search: ${p.allow_marketplace_search ? '✓' : '✗'} | Account mgmt: ${p.allow_openclaw_account_management ? '✓' : '✗'}</p>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + e.message + '</p>';
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
                <h3>${s.display_name}</h3>
                <p>Domain: ${s.domain}</p>
                <p>Reason: ${s.reason}</p>
                <button class="approve" onclick="approveS('${s.suggestion_id}')">Approve</button>
                <button class="reject" onclick="rejectS('${s.suggestion_id}')">Reject</button>
                <button onclick="blockS('${s.suggestion_id}')">Block</button>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + e.message + '</p>';
    }
}

async function approveS(id) { await apiFetch('/api/platforms/suggestions/'+id+'/approve',{method:'POST'}); loadSuggestions(); loadPlatforms(); }
async function rejectS(id) { await apiFetch('/api/platforms/suggestions/'+id+'/reject',{method:'POST'}); loadSuggestions(); }
async function blockS(id) { await apiFetch('/api/platforms/suggestions/'+id+'/block',{method:'POST'}); loadSuggestions(); }

async function loadAccounts() {
    const list = document.getElementById('accounts-list');
    try {
        const data = await apiFetch('/api/openclaw/accounts');
        if (!data.accounts.length) {
            list.innerHTML = '<p style="color:#888">No OpenClaw accounts registered. AIVEN does not store platform credentials — accounts are managed by OpenClaw.</p>';
            return;
        }
        list.innerHTML = data.accounts.map(a => `
            <div class="card">
                <h3>${a.display_name || a.account_connection_id}</h3>
                <p>Platform: <span class="tag blue">${a.platform}</span></p>
                <p>Status: <span class="tag ${a.status==='connected'?'green':a.status==='revoked'?'red':'yellow'}">${a.status}</span></p>
                <p>Permissions: ${a.permissions.join(', ')}</p>
                <button onclick="revokeAccount('${a.account_connection_id}')">Revoke</button>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + e.message + '</p>';
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
    await apiFetch('/api/openclaw/accounts/'+id+'/revoke', {method:'POST'});
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
                <h3>Draft: ${d.draft_id}</h3>
                <p>To: ${d.target_role}</p>
                <p>Created by: ${d.created_by_agent}</p>
                <pre style="background:#f8f9fa;padding:8px;border-radius:4px;font-size:0.8rem;white-space:pre-wrap;margin:8px 0">${d.message_text}</pre>
                <button class="approve" onclick="approveDraft('${d.draft_id}')">✓ Approve & Send</button>
                <button class="reject" onclick="rejectDraft('${d.draft_id}')">✗ Reject</button>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<p style="color:red">Error: ' + e.message + '</p>';
    }
}

async function approveDraft(draftId) {
    try {
        const data = await apiFetch('/api/openclaw/drafts/'+draftId+'/approve', {method:'POST', body: JSON.stringify({approved_by:'user'})});
        alert('Approved and sent: ' + JSON.stringify(data));
        const projectId = document.getElementById('approval-project-id').value.trim();
        if (projectId) loadDrafts();
    } catch (e) { alert('Error: ' + e.message); }
}

async function rejectDraft(draftId) {
    try {
        await apiFetch('/api/openclaw/drafts/'+draftId+'/reject', {method:'POST'});
        alert('Draft rejected');
        const projectId = document.getElementById('approval-project-id').value.trim();
        if (projectId) loadDrafts();
    } catch (e) { alert('Error: ' + e.message); }
}

// Load initial state
window.onload = () => { loadProjects(); };
