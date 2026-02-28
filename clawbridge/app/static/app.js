/* ═══════════════════════════════════════════════
   ClawBridge - Frontend Application v1.5.1
   ═══════════════════════════════════════════════ */

const BASE_PATH = window.location.pathname.replace(/\/$/, '');

// ─── State ─────────────────────────────────────
let allDomains = {};
let exposedEntities = {};    // { entity_id: "read"|"confirm"|"control" }
let entityAnnotations = {};  // { entity_id: "description" }
let entityConstraints = {};  // { entity_id: { param: { min, max } } }
let entitySchedules = {};    // { entity_id: schedule_id }
let allSchedules = {};       // { schedule_id: { name, start, end, days } }
let entityGroups = {};       // { group_id: { name, entities, icon } }
let activeDomain = null;
let currentTab = 'dashboard';
let undoSnapshot = null;

const SENSITIVE_DOMAINS = ['lock', 'cover', 'alarm_control_panel', 'climate', 'valve'];
const READ_ONLY_DOMAINS = ['sensor', 'binary_sensor', 'weather', 'sun', 'zone', 'person', 'device_tracker', 'geo_location', 'air_quality', 'image'];
let pendingSensitiveCallback = null;

const DOMAIN_ICONS = {
  __exposed__: '⭐', __all__: '🌐',
  sensor: '📊', binary_sensor: '🔘', light: '💡', switch: '🔌',
  climate: '🌡️', cover: '🪟', fan: '🌀', lock: '🔒',
  media_player: '🎵', camera: '📷', vacuum: '🤖', weather: '🌤️',
  person: '👤', device_tracker: '📍', automation: '⚙️', script: '📜',
  scene: '🎬', input_boolean: '☑️', input_number: '🔢', input_select: '📋',
  input_text: '📝', timer: '⏱️', counter: '🔄', alert: '🚨',
  group: '📁', zone: '🗺️', sun: '☀️', water_heater: '🚿',
  humidifier: '💧', number: '🔢', select: '📋', button: '🔘',
  text: '📝', update: '🔄', remote: '📺', siren: '🔔',
  calendar: '📅', tts: '🗣️', image: '🖼️', stt: '🎤',
  conversation: '💬', todo: '✅', event: '📢', valve: '🔧',
  lawn_mower: '🌱', notify: '📣', tag: '🏷️', schedule: '📅',
  date: '📆', time: '🕐', datetime: '📅', wake_word: '🎤',
};

// ─── Theme ─────────────────────────────────────

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('clawbridge-theme', theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

// Apply saved theme immediately
(function() {
  const saved = localStorage.getItem('clawbridge-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
})();

// ─── Init ──────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadEntities();
  loadSettings();
  loadDashboard();
  document.getElementById('sensitive-confirm-check').addEventListener('change', (e) => {
    document.getElementById('sensitive-confirm-btn').disabled = !e.target.checked;
  });
});

// ─── Mobile Sidebar ─────────────────────────────

function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('open');
  document.getElementById('sidebar-backdrop').classList.toggle('show');
}

function closeSidebar() {
  document.querySelector('.sidebar').classList.remove('open');
  document.getElementById('sidebar-backdrop').classList.remove('show');
}

// ─── API Helpers ───────────────────────────────

async function apiGet(path) {
  const resp = await fetch(`${BASE_PATH}${path}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

async function apiPost(path, data) {
  const resp = await fetch(`${BASE_PATH}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

async function apiDelete(path) {
  const resp = await fetch(`${BASE_PATH}${path}`, { method: 'DELETE' });
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

// ─── Helpers ───────────────────────────────────

function getAllEntitiesFlat() { return Object.values(allDomains).flat(); }
function getExposedEntities() { return getAllEntitiesFlat().filter(e => exposedEntities[e.entity_id]); }
function countByAccess(level) { return Object.values(exposedEntities).filter(v => v === level).length; }

// ─── Load Entities ─────────────────────────────

async function loadEntities() {
  try {
    const data = await apiGet('/api/entities');
    allDomains = data.domains;
    exposedEntities = data.exposed_entities || {};
    entityAnnotations = data.annotations || {};
    entityConstraints = data.constraints || {};
    entitySchedules = data.entity_schedules || {};
    allSchedules = data.schedules || {};
    loadGroupsSidebar();
    renderDomainList();
    updateExposedCount();
    setStatus(true, `${getAllEntitiesFlat().length} entities loaded`);
    if (currentTab === 'entities') {
      if (Object.keys(exposedEntities).length > 0) {
        selectDomain('__exposed__');
      } else {
        const domains = Object.keys(allDomains).sort();
        if (domains.length > 0) selectDomain(domains[0]);
      }
    }
  } catch (err) {
    console.error('Failed to load entities:', err);
    setStatus(false, 'Failed to connect');
    const el = document.getElementById('loading');
    if (el) el.innerHTML = `<div class="empty-state"><div class="empty-icon"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div><h3>Connection Error</h3><p>Could not connect to Home Assistant.</p></div>`;
  }
}

// ─── Render Domain List ────────────────────────

function renderDomainList() {
  const list = document.getElementById('domain-list');
  const domains = Object.keys(allDomains).sort();
  const exposedCount = getExposedEntities().length;
  const totalCount = getAllEntitiesFlat().length;

  let html = '';
  html += `<div class="domain-item ${activeDomain === '__exposed__' ? 'active' : ''}" onclick="selectDomain('__exposed__')" data-domain="__exposed__" style="border-bottom:1px solid var(--border);margin-bottom:4px;padding-bottom:12px;">
    <span class="domain-icon">⭐</span><span class="domain-name" style="font-weight:600;">Exposed</span>
    <span class="domain-count" style="background:var(--success-dim);color:var(--success);">${exposedCount}</span></div>`;

  html += `<div class="domain-item ${activeDomain === '__all__' ? 'active' : ''}" onclick="selectDomain('__all__')" data-domain="__all__" style="border-bottom:1px solid var(--border);margin-bottom:4px;padding-bottom:12px;">
    <span class="domain-icon">🌐</span><span class="domain-name" style="font-weight:600;">All</span>
    <span class="domain-count">${totalCount}</span></div>`;

  html += domains.map(domain => {
    const count = allDomains[domain].length;
    const selectedCount = allDomains[domain].filter(e => exposedEntities[e.entity_id]).length;
    const icon = DOMAIN_ICONS[domain] || '📦';
    const isActive = domain === activeDomain ? 'active' : '';
    return `<div class="domain-item ${isActive}" onclick="selectDomain('${domain}')" data-domain="${domain}">
      <span class="domain-icon">${icon}</span><span class="domain-name">${domain}</span>
      <span class="domain-count">${selectedCount ? selectedCount + '/' : ''}${count}</span></div>`;
  }).join('');

  list.innerHTML = html;
}

// ─── Select Domain ─────────────────────────────

function selectDomain(domain) {
  activeDomain = domain;
  document.querySelectorAll('.domain-item').forEach(el => {
    el.classList.toggle('active', el.dataset.domain === domain);
  });
  const icon = DOMAIN_ICONS[domain] || '📦';
  const label = domain === '__exposed__' ? 'Exposed Entities' : domain === '__all__' ? 'All Entities' : domain;
  document.getElementById('status-domain').textContent = `${icon} ${label}`;
  renderEntityList();
  closeSidebar();
  // Auto-switch to entities tab on mobile when selecting a domain
  if (window.innerWidth <= 768 && currentTab !== 'entities') {
    switchTab('entities');
  }
}

// ─── Render Entity List (four-state toggle) ────

function renderEntityList() {
  const list = document.getElementById('entity-list');
  const searchTerm = document.getElementById('search-input').value.toLowerCase();

  let entities;
  if (searchTerm) {
    entities = getAllEntitiesFlat().filter(e =>
      e.friendly_name.toLowerCase().includes(searchTerm) || e.entity_id.toLowerCase().includes(searchTerm)
    );
  } else if (activeDomain === '__exposed__') {
    entities = getExposedEntities();
  } else if (activeDomain === '__all__') {
    entities = getAllEntitiesFlat();
  } else if (activeDomain && activeDomain.startsWith('group:')) {
    const groupId = activeDomain.slice(6);
    const group = entityGroups[groupId];
    const groupEntityIds = group ? new Set(group.entities || []) : new Set();
    entities = getAllEntitiesFlat().filter(e => groupEntityIds.has(e.entity_id));
  } else if (activeDomain && allDomains[activeDomain]) {
    entities = allDomains[activeDomain];
  } else {
    entities = [];
  }

  if (entities.length === 0) {
    const emptyMsg = searchTerm ? 'No matching entities.' : activeDomain === '__exposed__' ? 'No entities exposed yet.' : 'No entities in this domain.';
    list.innerHTML = `<div class="empty-state"><div class="empty-icon"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></div><h3>${searchTerm ? 'No results' : 'No entities'}</h3><p>${emptyMsg}</p></div>`;
    updateFilterStatus(0, 0);
    return;
  }

  list.innerHTML = entities.map(entity => {
    const access = exposedEntities[entity.entity_id] || null;
    const accessClass = access || '';
    const isSensitive = SENSITIVE_DOMAINS.includes(entity.domain);
    const domainBadge = (searchTerm || activeDomain === '__exposed__' || activeDomain === '__all__')
      ? `<span style="color:var(--text-3);font-size:10px;background:var(--bg-4);padding:1px 6px;border-radius:4px;font-family:var(--mono);">${entity.domain}</span>` : '';
    const sensitiveIcon = isSensitive && (access === 'control' || access === 'confirm') ? '<span class="sensitive-badge" title="Sensitive domain">⚠️</span>' : '';
    const isReadOnly = READ_ONLY_DOMAINS.includes(entity.domain);
    const annotation = entityAnnotations[entity.entity_id];
    const annotationLine = annotation ? `<div class="entity-annotation">${escapeHtml(annotation)}</div>` : '';
    const hasConstraints = entityConstraints[entity.entity_id];
    const schedule = entitySchedules[entity.entity_id];
    const scheduleInfo = schedule && allSchedules[schedule] ? allSchedules[schedule].name : '';

    return `<div class="entity-card ${accessClass}" data-entity="${entity.entity_id}">
      <div class="entity-access-toggle" onclick="event.stopPropagation()">
        <button class="access-btn ${access === null ? 'active' : ''}" onclick="setEntityAccess('${entity.entity_id}', null)" title="Not exposed">off</button>
        <button class="access-btn read ${access === 'read' ? 'active' : ''}" onclick="setEntityAccess('${entity.entity_id}', 'read')" title="AI can see state">read</button>
        ${isReadOnly ? '' : `<button class="access-btn confirm ${access === 'confirm' ? 'active' : ''}" onclick="setEntityAccess('${entity.entity_id}', 'confirm')" title="AI can request actions (requires approval)">ask</button>
        <button class="access-btn control ${access === 'control' ? 'active' : ''}" onclick="setEntityAccess('${entity.entity_id}', 'control')" title="AI can call services directly">ctrl</button>`}
      </div>
      <div class="entity-info">
        <div class="entity-name">${escapeHtml(entity.friendly_name)}${domainBadge}${sensitiveIcon}${scheduleInfo ? `<span style="font-size:9px;color:var(--confirm);font-family:var(--mono);">${escapeHtml(scheduleInfo)}</span>` : ''}${hasConstraints ? '<span style="font-size:9px;color:var(--warning);" title="Has parameter constraints">⛓</span>' : ''}</div>
        <div class="entity-id">${entity.entity_id}</div>
        ${annotationLine}
      </div>
      <div class="entity-actions">
        <button class="entity-action-btn" onclick="event.stopPropagation();showAnnotationModal('${entity.entity_id}')" title="Add description">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        ${(access === 'control' || access === 'confirm') ? `<button class="entity-action-btn" onclick="event.stopPropagation();showConstraintsModal('${entity.entity_id}')" title="Set parameter constraints">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/></svg>
        </button>` : ''}
      </div>
      <div class="entity-state">
        <span class="state-value">${escapeHtml(entity.state)}</span>
        ${entity.unit_of_measurement ? `<span class="state-unit">${escapeHtml(entity.unit_of_measurement)}</span>` : ''}
      </div>
    </div>`;
  }).join('');

  const selectedInView = entities.filter(e => exposedEntities[e.entity_id]).length;
  updateFilterStatus(entities.length, selectedInView);
}

// ─── Set Entity Access ─────────────────────────

function setEntityAccess(entityId, access) {
  const domain = entityId.split('.')[0];
  if ((access === 'control' || access === 'confirm') && READ_ONLY_DOMAINS.includes(domain)) {
    return; // Read-only domains cannot be controlled
  }
  if ((access === 'control' || access === 'confirm') && SENSITIVE_DOMAINS.includes(domain)) {
    pendingSensitiveCallback = () => { _applyAccess(entityId, access); };
    document.getElementById('sensitive-modal-text').textContent =
      `You are about to grant AI ${access === 'confirm' ? 'confirmation-required' : 'direct'} control over "${entityId}".`;
    document.getElementById('sensitive-confirm-check').checked = false;
    document.getElementById('sensitive-confirm-btn').disabled = true;
    document.getElementById('sensitive-modal').classList.add('show');
    return;
  }
  _applyAccess(entityId, access);
}

function _applyAccess(entityId, access) {
  if (access === null) { delete exposedEntities[entityId]; }
  else { exposedEntities[entityId] = access; }
  renderEntityList();
  renderDomainList();
  updateExposedCount();
  scheduleAutoSave();
}

function confirmSensitiveModal() {
  document.getElementById('sensitive-modal').classList.remove('show');
  if (pendingSensitiveCallback) { pendingSensitiveCallback(); pendingSensitiveCallback = null; }
}

function cancelSensitiveModal() {
  document.getElementById('sensitive-modal').classList.remove('show');
  pendingSensitiveCallback = null;
}

// ─── Auto-Save (debounced) ─────────────────────

let autoSaveTimer = null;

function scheduleAutoSave() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(async () => {
    try {
      await apiPost('/api/selection', { exposed_entities: exposedEntities });
      showToast(`Auto-saved! ${Object.keys(exposedEntities).length} entities exposed.`);
    } catch (err) { console.error('Auto-save failed:', err); }
  }, 500);
}

// ─── Undo ───────────────────────────────────────

function pushUndo() { undoSnapshot = { ...exposedEntities }; }

function undo() {
  if (!undoSnapshot) return;
  exposedEntities = { ...undoSnapshot };
  undoSnapshot = null;
  renderEntityList(); renderDomainList(); updateExposedCount();
  scheduleAutoSave();
  showToast(`Restored! ${Object.keys(exposedEntities).length} entities exposed.`);
}

// ─── Select / Deselect All ─────────────────────

function selectAllVisible(access) {
  const entities = getVisibleEntities();
  if (entities.length === 0) return;
  pushUndo();
  entities.forEach(e => { exposedEntities[e.entity_id] = access; });
  renderEntityList(); renderDomainList(); updateExposedCount();
  scheduleAutoSave();
  showUndoToast(`Set ${entities.length} entities to "${access}".`);
}

function deselectAllVisible() {
  const entities = getVisibleEntities();
  if (entities.length === 0) return;
  const searchTerm = document.getElementById('search-input').value.toLowerCase();
  if (activeDomain === '__exposed__' && !searchTerm) {
    if (!confirm(`Remove all ${entities.length} exposed entities?`)) return;
  }
  pushUndo();
  entities.forEach(e => { delete exposedEntities[e.entity_id]; });
  renderEntityList(); renderDomainList(); updateExposedCount();
  scheduleAutoSave();
  showUndoToast(`Removed ${entities.length} entities.`);
}

function getVisibleEntities() {
  const searchTerm = document.getElementById('search-input').value.toLowerCase();
  if (searchTerm) {
    return getAllEntitiesFlat().filter(e =>
      e.friendly_name.toLowerCase().includes(searchTerm) || e.entity_id.toLowerCase().includes(searchTerm)
    );
  } else if (activeDomain === '__exposed__') { return getExposedEntities(); }
  else if (activeDomain === '__all__') { return getAllEntitiesFlat(); }
  else if (activeDomain && activeDomain.startsWith('group:')) {
    const groupId = activeDomain.slice(6);
    const group = entityGroups[groupId];
    const ids = group ? new Set(group.entities || []) : new Set();
    return getAllEntitiesFlat().filter(e => ids.has(e.entity_id));
  }
  else if (activeDomain && allDomains[activeDomain]) { return allDomains[activeDomain]; }
  return [];
}

// ─── Save Selection ────────────────────────────

async function saveSelection() {
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:14px;height:14px;border-width:2px;"></div> Saving...';
  try {
    await apiPost('/api/selection', { exposed_entities: exposedEntities });
    showToast(`Saved! ${Object.keys(exposedEntities).length} entities (${countByAccess('read')} read, ${countByAccess('confirm')} confirm, ${countByAccess('control')} control).`);
    closeSidebar();
  } catch (err) { showToast('Failed to save.', true); console.error(err); }
  btn.disabled = false;
  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> Save`;
}

function filterEntities() { renderEntityList(); }

// ─── Tabs ──────────────────────────────────────

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  ['dashboard', 'entities', 'audit', 'security', 'settings'].forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  if (tab === 'dashboard') loadDashboard();
  if (tab === 'audit') loadAuditLogs();
  if (tab === 'security') { loadApiKeys(); loadSchedules(); loadPendingActions(); loadGroups(); }
  if (tab === 'settings') loadPresets();
  if (tab === 'entities' && !activeDomain) {
    if (Object.keys(exposedEntities).length > 0) selectDomain('__exposed__');
    else { const d = Object.keys(allDomains).sort(); if (d.length) selectDomain(d[0]); }
  }
}

// ─── Dashboard ─────────────────────────────────

async function loadDashboard() {
  const container = document.getElementById('dashboard-content');
  try {
    const stats = await apiGet('/api/stats');
    const maxHourly = Math.max(...stats.hourly, 1);
    const hourlyBars = stats.hourly.map((v, i) =>
      `<div class="dash-bar" style="height:${Math.max(2, (v / maxHourly) * 100)}%" title="${stats.hourly.length - i}h ago: ${v} calls"></div>`
    ).reverse().join('');

    container.innerHTML = `
      <div class="dash-grid">
        <div class="dash-card"><div class="dash-label">Calls (24h)</div><div class="dash-value">${stats.total_24h}</div><div class="dash-sub">${stats.total_all_time} all time</div></div>
        <div class="dash-card"><div class="dash-label">Success Rate</div><div class="dash-value">${stats.success_rate_24h}%</div><div class="dash-sub">${stats.results_24h?.denied || 0} denied</div></div>
        <div class="dash-card"><div class="dash-label">Avg Response</div><div class="dash-value">${stats.avg_response_ms}ms</div><div class="dash-sub">${stats.ws_clients} WS clients</div></div>
        <div class="dash-card"><div class="dash-label">Exposed</div><div class="dash-value">${stats.total_exposed}</div><div class="dash-sub">${stats.total_read}r ${stats.total_confirm}c ${stats.total_control}w</div></div>
      </div>
      <div class="dash-chart-container"><div class="dash-chart-title">Calls per hour (last 24h)</div><div class="dash-bar-chart">${hourlyBars}</div></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <div class="dash-list"><div class="dash-list-title">Most Called Entities</div>${
          (stats.top_entities || []).map(([e, c]) => `<div class="dash-list-item"><span class="list-entity">${escapeHtml(e)}</span><span class="list-count">${c}</span></div>`).join('') || '<div class="dash-list-item"><span class="list-entity" style="color:var(--text-3);">No data yet</span></div>'
        }</div>
        <div class="dash-list"><div class="dash-list-title">Most Denied Entities</div>${
          (stats.top_denied || []).map(([e, c]) => `<div class="dash-list-item"><span class="list-entity">${escapeHtml(e)}</span><span class="list-count" style="color:var(--warning);">${c}</span></div>`).join('') || '<div class="dash-list-item"><span class="list-entity" style="color:var(--text-3);">None denied</span></div>'
        }</div>
      </div>`;
  } catch (err) {
    console.error('Failed to load dashboard:', err);
    container.innerHTML = '<div class="empty-state"><h3>Could not load stats</h3></div>';
  }
}

// ─── Audit ─────────────────────────────────────

async function loadAuditLogs() {
  const listEl = document.getElementById('audit-list');
  try {
    const data = await apiGet('/api/audit/logs?limit=200');
    const logs = data.logs || [];
    if (logs.length === 0) {
      listEl.innerHTML = `<div class="empty-state"><div class="empty-icon"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div><h3>No audit logs</h3><p>Service calls from AI agents will appear here.</p></div>`;
      return;
    }
    listEl.innerHTML = `<table class="audit-table">
      <thead><tr><th>Time</th><th>Entity</th><th>Service</th><th>Result</th><th>IP</th></tr></thead>
      <tbody>${logs.map(l => {
        const ts = l.timestamp ? new Date(l.timestamp).toLocaleString() : '-';
        const rc = l.result === 'success' ? 'audit-success' : l.result === 'denied' ? 'audit-denied' : l.result === 'clamped' ? 'audit-clamped' : l.result === 'pending' ? 'audit-pending' : 'audit-error';
        return `<tr><td>${escapeHtml(ts)}</td><td>${escapeHtml(l.entity_id || '-')}</td><td>${escapeHtml((l.domain||'')+'.'+(l.service||''))}</td><td><span class="${rc}">${escapeHtml(l.result||'-')}</span></td><td>${escapeHtml(l.source_ip||'-')}</td></tr>`;
      }).join('')}</tbody></table>`;
  } catch (err) {
    console.error('Failed to load audit logs:', err);
    listEl.innerHTML = '<div class="empty-state"><h3>Error loading logs</h3></div>';
  }
}

async function clearAuditLogs() {
  if (!confirm('Clear all audit logs?')) return;
  try { await apiDelete('/api/audit/logs'); showToast('Audit log cleared.'); loadAuditLogs(); }
  catch (err) { showToast('Failed to clear audit log.', true); }
}

// ─── Annotations ───────────────────────────────

let annotationEntityId = null;

function showAnnotationModal(entityId) {
  annotationEntityId = entityId;
  document.getElementById('annotation-entity-id').textContent = entityId;
  document.getElementById('annotation-text').value = entityAnnotations[entityId] || '';
  document.getElementById('annotation-modal').classList.add('show');
  document.getElementById('annotation-text').focus();
}

function hideAnnotationModal() { document.getElementById('annotation-modal').classList.remove('show'); }

async function saveAnnotation() {
  const text = document.getElementById('annotation-text').value.trim();
  try {
    await apiPost('/api/annotation', { entity_id: annotationEntityId, annotation: text });
    if (text) entityAnnotations[annotationEntityId] = text;
    else delete entityAnnotations[annotationEntityId];
    hideAnnotationModal();
    renderEntityList();
    showToast('Annotation saved.');
  } catch (err) { showToast('Failed to save annotation.', true); }
}

// ─── Constraints ───────────────────────────────

let constraintsEntityId = null;

function showConstraintsModal(entityId) {
  constraintsEntityId = entityId;
  document.getElementById('constraints-entity-id').textContent = entityId;
  const existing = entityConstraints[entityId] || {};
  const editor = document.getElementById('constraints-editor');

  // Find the entity to check which attributes it actually supports
  const entity = getAllEntitiesFlat().find(e => e.entity_id === entityId);
  const attrKeys = entity && entity.attribute_keys ? entity.attribute_keys : [];

  // Candidate parameters based on domain
  const domain = entityId.split('.')[0];
  const candidates = [];
  if (['light'].includes(domain)) candidates.push('brightness', 'color_temp');
  if (['climate'].includes(domain)) candidates.push('temperature', 'target_temp_high', 'target_temp_low', 'humidity');
  if (['fan'].includes(domain)) candidates.push('percentage');
  if (['cover'].includes(domain)) candidates.push('position', 'tilt_position');
  if (['number', 'input_number'].includes(domain)) candidates.push('value');

  // Filter to only params the entity actually has
  const params = candidates.filter(p => attrKeys.includes(p));
  if (params.length === 0 && candidates.length === 0) params.push('value');

  // Keep any previously saved constraints even if not in current attributes
  for (const p of Object.keys(existing)) {
    if (!params.includes(p)) params.push(p);
  }

  editor.innerHTML = params.map(p => {
    const c = existing[p] || {};
    return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <span style="font-family:var(--mono);font-size:11px;color:var(--text-2);width:120px;">${escapeHtml(p)}</span>
      <label style="font-size:10px;color:var(--text-3);">min</label>
      <input type="number" class="number-input constraint-input" data-param="${p}" data-type="min" value="${c.min != null ? c.min : ''}" style="width:70px;">
      <label style="font-size:10px;color:var(--text-3);">max</label>
      <input type="number" class="number-input constraint-input" data-param="${p}" data-type="max" value="${c.max != null ? c.max : ''}" style="width:70px;">
    </div>`;
  }).join('');

  document.getElementById('constraints-modal').classList.add('show');
}

function hideConstraintsModal() { document.getElementById('constraints-modal').classList.remove('show'); }

async function saveConstraintsFromModal() {
  const inputs = document.querySelectorAll('.constraint-input');
  const constraints = {};
  inputs.forEach(input => {
    const param = input.dataset.param;
    const type = input.dataset.type;
    const val = input.value.trim();
    if (!constraints[param]) constraints[param] = {};
    if (val !== '') constraints[param][type] = parseFloat(val);
  });
  // Remove empty constraints
  const clean = {};
  for (const [p, c] of Object.entries(constraints)) {
    if (c.min != null || c.max != null) clean[p] = c;
  }
  try {
    await apiPost('/api/constraints', { entity_id: constraintsEntityId, constraints: clean });
    if (Object.keys(clean).length > 0) entityConstraints[constraintsEntityId] = clean;
    else delete entityConstraints[constraintsEntityId];
    hideConstraintsModal();
    renderEntityList();
    showToast('Constraints saved.');
  } catch (err) { showToast('Failed to save constraints.', true); }
}

// ─── API Keys ──────────────────────────────────

async function loadApiKeys() {
  try {
    const data = await apiGet('/api/keys');
    const keys = data.keys || [];
    const el = document.getElementById('api-keys-list');
    if (keys.length === 0) {
      el.innerHTML = '<div class="empty-state-sm">No API keys configured. All access is open.</div>';
      return;
    }
    el.innerHTML = keys.map(k => `<div class="key-item">
      <div class="key-item-info">
        <span class="key-item-name">${escapeHtml(k.name)}</span>
        <span class="key-item-meta">${escapeHtml(k.key_preview)} | ${k.entity_count} entities | ${k.rate_limit || 'global'} rpm</span>
      </div>
      <button class="btn btn-danger btn-xs" onclick="deleteApiKey('${escapeAttr(k.key_id)}')">delete</button>
    </div>`).join('');
  } catch (err) { console.error('Failed to load API keys:', err); }
}

function showCreateKeyModal() {
  document.getElementById('key-name-input').value = '';
  document.getElementById('key-result').style.display = 'none';
  document.getElementById('key-modal').classList.add('show');
  document.getElementById('key-name-input').focus();
}

function hideKeyModal() { document.getElementById('key-modal').classList.remove('show'); }

async function createApiKey() {
  const name = document.getElementById('key-name-input').value.trim();
  if (!name) return;
  try {
    const data = await apiPost('/api/keys', { name });
    document.getElementById('key-result').style.display = 'block';
    document.getElementById('key-result').textContent = `Key created! Copy this (shown once):\n${data.key}`;
    loadApiKeys();
  } catch (err) { showToast('Failed to create API key.', true); }
}

async function deleteApiKey(keyId) {
  if (!confirm('Delete this API key?')) return;
  try { await apiDelete(`/api/keys/${keyId}`); showToast('API key deleted.'); loadApiKeys(); }
  catch (err) { showToast('Failed to delete key.', true); }
}

// ─── Schedules ─────────────────────────────────

async function loadSchedules() {
  try {
    const data = await apiGet('/api/schedules');
    allSchedules = data.schedules || {};
    entitySchedules = data.entity_schedules || {};
    const el = document.getElementById('schedules-list');
    const entries = Object.entries(allSchedules);
    if (entries.length === 0) {
      el.innerHTML = '<div class="empty-state-sm">No schedules configured. AI can act at any time.</div>';
      return;
    }
    const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    el.innerHTML = entries.map(([id, s]) => {
      const days = (s.days || []).map(d => dayNames[d] || '?').join(', ');
      const assigned = Object.values(entitySchedules).filter(sid => sid === id).length;
      return `<div class="schedule-item">
        <div class="schedule-item-info">
          <span class="schedule-item-name">${escapeHtml(s.name)}</span>
          <span class="schedule-item-meta">${s.start}-${s.end} | ${days} | ${assigned} entities</span>
        </div>
        <button class="btn btn-danger btn-xs" onclick="deleteSchedule('${escapeAttr(id)}')">delete</button>
      </div>`;
    }).join('');
  } catch (err) { console.error('Failed to load schedules:', err); }
}

function showCreateScheduleModal() {
  document.getElementById('schedule-name-input').value = '';
  document.getElementById('schedule-start').value = '06:00';
  document.getElementById('schedule-end').value = '23:00';
  document.querySelectorAll('#schedule-days input').forEach(cb => { cb.checked = true; });
  document.getElementById('schedule-modal').classList.add('show');
}

function hideScheduleModal() { document.getElementById('schedule-modal').classList.remove('show'); }

async function createSchedule() {
  const name = document.getElementById('schedule-name-input').value.trim();
  if (!name) return;
  const start = document.getElementById('schedule-start').value;
  const end = document.getElementById('schedule-end').value;
  const days = Array.from(document.querySelectorAll('#schedule-days input:checked')).map(cb => parseInt(cb.value));
  try {
    await apiPost('/api/schedules', { name, start, end, days });
    hideScheduleModal();
    showToast('Schedule created.');
    loadSchedules();
  } catch (err) { showToast('Failed to create schedule.', true); }
}

async function deleteSchedule(scheduleId) {
  if (!confirm('Delete this schedule?')) return;
  try { await apiDelete(`/api/schedules/${scheduleId}`); showToast('Schedule deleted.'); loadSchedules(); }
  catch (err) { showToast('Failed to delete schedule.', true); }
}

// ─── Pending Actions ───────────────────────────

async function loadPendingActions() {
  try {
    const data = await apiGet('/api/pending-actions');
    const pending = data.pending || {};
    const el = document.getElementById('pending-actions-list');
    const entries = Object.entries(pending);
    if (entries.length === 0) {
      el.innerHTML = '<div class="empty-state-sm">No pending actions.</div>';
      return;
    }
    el.innerHTML = entries.map(([id, a]) => `<div class="action-item">
      <div class="action-item-info">
        <span class="key-item-name">${escapeHtml(a.domain)}.${escapeHtml(a.service)} on ${escapeHtml(a.entity_id)}</span>
        <span class="key-item-meta">${a.age_seconds}s ago</span>
      </div>
      <div style="display:flex;gap:4px;">
        <button class="btn btn-success btn-xs" onclick="approveAction('${escapeAttr(id)}')">approve</button>
        <button class="btn btn-danger btn-xs" onclick="denyAction('${escapeAttr(id)}')">deny</button>
      </div>
    </div>`).join('');
  } catch (err) { console.error('Failed to load pending actions:', err); }
}

async function approveAction(actionId) {
  try { await apiPost(`/api/actions/${actionId}/approve`, {}); showToast('Action approved.'); loadPendingActions(); }
  catch (err) { showToast('Failed to approve action.', true); }
}

async function denyAction(actionId) {
  try { await apiPost(`/api/actions/${actionId}/deny`, {}); showToast('Action denied.'); loadPendingActions(); }
  catch (err) { showToast('Failed to deny action.', true); }
}

// ─── Presets ───────────────────────────────────

async function loadPresets() {
  try {
    const data = await apiGet('/api/presets');
    renderPresets(data.presets || {});
  } catch (err) { console.error('Failed to load presets:', err); }
}

function renderPresets(presets) {
  const list = document.getElementById('preset-list');
  const entries = Object.entries(presets);
  if (entries.length === 0) {
    list.innerHTML = '<div class="empty-state-sm" style="padding:20px;">No presets saved.</div>';
    return;
  }
  list.innerHTML = entries.map(([name, data]) => {
    const count = typeof data === 'object' && !Array.isArray(data) ? Object.keys(data).length : (Array.isArray(data) ? data.length : 0);
    return `<div class="preset-item"><div><span class="preset-name">${escapeHtml(name)}</span><span class="preset-count">${count} entities</span></div>
      <div class="preset-actions"><button class="btn btn-sm btn-primary" onclick="applyPreset('${escapeAttr(name)}')">Load</button>
      <button class="btn btn-sm btn-danger" onclick="deletePreset('${escapeAttr(name)}')">Delete</button></div></div>`;
  }).join('');
}

function showSavePresetModal() {
  document.getElementById('preset-modal').classList.add('show');
  document.getElementById('preset-name-input').value = '';
  document.getElementById('preset-name-input').focus();
}

function hidePresetModal() { document.getElementById('preset-modal').classList.remove('show'); }

async function savePreset() {
  const name = document.getElementById('preset-name-input').value.trim();
  if (!name) return;
  try { await apiPost('/api/presets', { name, entities: exposedEntities }); showToast(`Preset "${name}" saved.`); hidePresetModal(); loadPresets(); }
  catch (err) { showToast('Failed to save preset.', true); }
}

async function applyPreset(name) {
  try {
    const data = await apiGet(`/api/presets/${encodeURIComponent(name)}`);
    const entities = data.entities || {};
    if (typeof entities === 'object' && !Array.isArray(entities)) { exposedEntities = entities; }
    else if (Array.isArray(entities)) { exposedEntities = {}; entities.forEach(eid => { exposedEntities[eid] = 'read'; }); }
    renderEntityList(); renderDomainList(); updateExposedCount(); scheduleAutoSave();
    showToast(`Loaded preset "${name}".`);
    switchTab('entities');
  } catch (err) { showToast('Failed to load preset.', true); }
}

async function deletePreset(name) {
  if (!confirm(`Delete preset "${name}"?`)) return;
  try { await apiDelete(`/api/presets/${encodeURIComponent(name)}`); showToast(`Preset "${name}" deleted.`); loadPresets(); }
  catch (err) { showToast('Failed to delete preset.', true); }
}

// ─── Settings ──────────────────────────────────

async function loadSettings() {
  try {
    const data = await apiGet('/api/settings');
    document.getElementById('setting-refresh').value = data.refresh_interval || 5;
    document.getElementById('setting-filter-unavailable').checked = data.filter_unavailable !== false;
    document.getElementById('setting-compact').checked = data.compact_mode === true;
    document.getElementById('setting-audit-enabled').checked = data.audit_enabled !== false;
    document.getElementById('setting-audit-retention').value = data.audit_retention_days || 30;
    document.getElementById('setting-rate-limit').value = data.rate_limit_per_minute || 60;
    document.getElementById('setting-allowed-ips').value = (data.allowed_ips || []).join(', ');
    document.getElementById('setting-confirm-timeout').value = data.confirm_timeout_seconds || 120;
    document.getElementById('setting-confirm-notify').value = data.confirm_notify_service || '';
    document.getElementById('setting-ai-name').value = data.ai_name || '';
  } catch (err) { console.error('Failed to load settings:', err); }
}

async function saveSettings() {
  const ipsRaw = document.getElementById('setting-allowed-ips').value;
  const ips = ipsRaw.split(',').map(s => s.trim()).filter(Boolean);
  const settings = {
    refresh_interval: parseInt(document.getElementById('setting-refresh').value, 10),
    filter_unavailable: document.getElementById('setting-filter-unavailable').checked,
    compact_mode: document.getElementById('setting-compact').checked,
    audit_enabled: document.getElementById('setting-audit-enabled').checked,
    audit_retention_days: parseInt(document.getElementById('setting-audit-retention').value, 10),
    rate_limit_per_minute: parseInt(document.getElementById('setting-rate-limit').value, 10),
    allowed_ips: ips,
    confirm_timeout_seconds: parseInt(document.getElementById('setting-confirm-timeout').value, 10),
    confirm_notify_service: document.getElementById('setting-confirm-notify').value.trim(),
    ai_name: document.getElementById('setting-ai-name').value.trim(),
  };
  try { await apiPost('/api/settings', settings); showToast('Settings saved.'); }
  catch (err) { showToast('Failed to save settings.', true); }
}

// ─── Export / Import ───────────────────────────

async function exportConfig() {
  try {
    const data = await apiGet('/api/config/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'clawbridge_config.json'; a.click();
    URL.revokeObjectURL(url);
    showToast('Configuration exported.');
  } catch (err) { showToast('Failed to export config.', true); }
}

async function importConfig(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const data = JSON.parse(e.target.result);
      await apiPost('/api/config/import', data);
      showToast('Configuration imported. Reloading...');
      setTimeout(() => location.reload(), 1000);
    } catch (err) { showToast('Failed to import config.', true); }
  };
  reader.readAsText(file);
  event.target.value = '';
}

// ─── UI Helpers ────────────────────────────────

function updateExposedCount() {
  const total = Object.keys(exposedEntities).length;
  const readCount = countByAccess('read');
  const confirmCount = countByAccess('confirm');
  const controlCount = countByAccess('control');
  document.getElementById('exposed-count').textContent = total;
  document.getElementById('read-count').textContent = readCount;
  document.getElementById('confirm-count').textContent = confirmCount;
  document.getElementById('control-count').textContent = controlCount;
  // Bottom dock pills
  document.getElementById('dock-read').textContent = readCount;
  document.getElementById('dock-confirm').textContent = confirmCount;
  document.getElementById('dock-control').textContent = controlCount;
}

function updateFilterStatus(total, selected) {
  document.getElementById('status-filter').textContent = `${total} shown, ${selected} selected`;
}

function setStatus(connected, text) {
  document.getElementById('status-dot').classList.toggle('disconnected', !connected);
  document.getElementById('status-text').textContent = text;
}

let toastTimer = null;

function showToast(message, isError = false) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = 'toast show' + (isError ? ' error' : '');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}

function showUndoToast(message) {
  const toast = document.getElementById('toast');
  toast.innerHTML = `${escapeHtml(message)} <button class="toast-undo-btn" onclick="undo()">UNDO</button>`;
  toast.className = 'toast show';
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 8000);
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// ─── Entity Groups ────────────────────────────

let editingGroupId = null;

async function loadGroupsSidebar() {
  try {
    const data = await apiGet('/api/groups');
    entityGroups = data.groups || {};
    renderGroupSidebar();
  } catch (err) { console.error('Failed to load groups:', err); }
}

async function loadGroups() {
  try {
    const data = await apiGet('/api/groups');
    entityGroups = data.groups || {};
    renderGroupSidebar();
    renderGroupsList();
  } catch (err) { console.error('Failed to load groups:', err); }
}

function renderGroupSidebar() {
  const container = document.getElementById('group-list');
  const groupIds = Object.keys(entityGroups);
  if (groupIds.length === 0) { container.innerHTML = ''; return; }

  let html = '<div style="padding:4px 0;border-bottom:1px solid var(--border);margin-bottom:4px;">';
  html += '<div style="font-size:9px;text-transform:uppercase;color:var(--text-3);padding:4px 12px;letter-spacing:1px;">Groups</div>';
  groupIds.forEach(gid => {
    const group = entityGroups[gid];
    const icon = group.icon || '📁';
    const count = (group.entities || []).length;
    const isActive = activeDomain === `group:${gid}` ? 'active' : '';
    html += `<div class="domain-item ${isActive}" onclick="selectGroup('${escapeAttr(gid)}')" data-domain="group:${gid}">
      <span class="domain-icon">${icon}</span><span class="domain-name">${escapeHtml(group.name)}</span>
      <span class="domain-count">${count}</span></div>`;
  });
  html += '</div>';
  container.innerHTML = html;
}

function selectGroup(groupId) {
  activeDomain = `group:${groupId}`;
  document.querySelectorAll('.domain-item').forEach(el => {
    el.classList.toggle('active', el.dataset.domain === activeDomain);
  });
  const group = entityGroups[groupId];
  const icon = group ? (group.icon || '📁') : '📁';
  const label = group ? group.name : groupId;
  document.getElementById('status-domain').textContent = `${icon} ${label}`;
  renderEntityList();
  closeSidebar();
  if (window.innerWidth <= 768 && currentTab !== 'entities') {
    switchTab('entities');
  }
}

function renderGroupsList() {
  const el = document.getElementById('groups-list');
  const entries = Object.entries(entityGroups);
  if (entries.length === 0) {
    el.innerHTML = '<div class="empty-state-sm">No groups configured.</div>';
    return;
  }
  el.innerHTML = entries.map(([id, g]) => {
    const count = (g.entities || []).length;
    return `<div class="group-item">
      <div class="group-item-info">
        <span class="group-item-icon">${g.icon || '📁'}</span>
        <span class="key-item-name">${escapeHtml(g.name)}</span>
        <span class="key-item-meta">${count} entities</span>
      </div>
      <div class="group-item-actions">
        <button class="btn btn-xs" onclick="setGroupAccess('${escapeAttr(id)}','read')" title="Set all to read">R</button>
        <button class="btn btn-xs" onclick="setGroupAccess('${escapeAttr(id)}','confirm')" title="Set all to confirm">C</button>
        <button class="btn btn-xs" onclick="setGroupAccess('${escapeAttr(id)}','control')" title="Set all to control">W</button>
        <button class="btn btn-xs" onclick="setGroupAccess('${escapeAttr(id)}','off')" title="Turn off all">Off</button>
        <button class="btn btn-xs" onclick="showEditGroupModal('${escapeAttr(id)}')" title="Edit group">edit</button>
        <button class="btn btn-danger btn-xs" onclick="deleteGroup('${escapeAttr(id)}')">del</button>
      </div>
    </div>`;
  }).join('');
}

function showCreateGroupModal() {
  editingGroupId = null;
  document.getElementById('group-modal-title').textContent = 'Create Group';
  document.getElementById('group-name-input').value = '';
  document.getElementById('group-icon-input').value = '';
  document.getElementById('group-save-btn').textContent = 'create';
  renderGroupEntityPicker([]);
  document.getElementById('group-modal').classList.add('show');
  document.getElementById('group-name-input').focus();
}

function showEditGroupModal(groupId) {
  editingGroupId = groupId;
  const group = entityGroups[groupId];
  if (!group) return;
  document.getElementById('group-modal-title').textContent = 'Edit Group';
  document.getElementById('group-name-input').value = group.name || '';
  document.getElementById('group-icon-input').value = group.icon || '';
  document.getElementById('group-save-btn').textContent = 'save';
  renderGroupEntityPicker(group.entities || []);
  document.getElementById('group-modal').classList.add('show');
}

function hideGroupModal() { document.getElementById('group-modal').classList.remove('show'); }

function renderGroupEntityPicker(selectedEntities) {
  const picker = document.getElementById('group-entity-picker');
  const selected = new Set(selectedEntities);
  const allEnts = getAllEntitiesFlat().sort((a, b) => a.entity_id.localeCompare(b.entity_id));
  picker.innerHTML = allEnts.map(e => {
    const checked = selected.has(e.entity_id) ? 'checked' : '';
    return `<label class="group-picker-item"><input type="checkbox" value="${escapeAttr(e.entity_id)}" ${checked}><span>${escapeHtml(e.friendly_name)}</span><span class="group-picker-id">${e.entity_id}</span></label>`;
  }).join('');
}

async function saveGroup() {
  const name = document.getElementById('group-name-input').value.trim();
  if (!name) { showToast('Group name required.', true); return; }
  const icon = document.getElementById('group-icon-input').value.trim();
  const entities = Array.from(document.querySelectorAll('#group-entity-picker input:checked')).map(cb => cb.value);

  try {
    if (editingGroupId) {
      await apiPost(`/api/groups/${editingGroupId}`, { name, icon, entities });
      showToast('Group updated.');
    } else {
      await apiPost('/api/groups', { name, icon, entities });
      showToast('Group created.');
    }
    hideGroupModal();
    loadGroups();
    renderGroupSidebar();
  } catch (err) { showToast('Failed to save group.', true); }
}

async function deleteGroup(groupId) {
  if (!confirm('Delete this group?')) return;
  try {
    await apiDelete(`/api/groups/${groupId}`);
    showToast('Group deleted.');
    loadGroups();
  } catch (err) { showToast('Failed to delete group.', true); }
}

async function setGroupAccess(groupId, level) {
  try {
    const data = await apiPost(`/api/groups/${groupId}/access`, { access_level: level });
    showToast(`Set ${data.changed} entities to "${level}".`);
    await loadEntities();
    loadGroups();
  } catch (err) { showToast('Failed to set group access.', true); }
}

