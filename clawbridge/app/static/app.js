/* ═══════════════════════════════════════════════
   ClawBridge - Frontend Application (Air Gap)
   ═══════════════════════════════════════════════ */

const BASE_PATH = window.location.pathname.replace(/\/$/, '');

// ─── State ─────────────────────────────────────
let allDomains = {};
// exposedEntities: { entity_id: "read"|"control" }
let exposedEntities = {};
let activeDomain = null;
let currentTab = 'entities';
let undoSnapshot = null;

// Sensitive domains that need confirmation before granting control
const SENSITIVE_DOMAINS = ['lock', 'cover', 'alarm_control_panel', 'climate', 'valve'];
let pendingSensitiveCallback = null;

// Domain icons
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

// ─── Init ──────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadEntities();
  loadSettings();
  document.getElementById('sensitive-confirm-check').addEventListener('change', (e) => {
    document.getElementById('sensitive-confirm-btn').disabled = !e.target.checked;
  });
});

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

function getExposedEntities() {
  return getAllEntitiesFlat().filter(e => exposedEntities[e.entity_id]);
}

function countByAccess(level) {
  return Object.values(exposedEntities).filter(v => v === level).length;
}

// ─── Load Entities ─────────────────────────────

async function loadEntities() {
  try {
    const data = await apiGet('/api/entities');
    allDomains = data.domains;
    exposedEntities = data.exposed_entities || {};
    renderDomainList();
    updateExposedCount();
    setStatus(true, `${getAllEntitiesFlat().length} entities loaded`);
    if (Object.keys(exposedEntities).length > 0) {
      selectDomain('__exposed__');
    } else {
      const domains = Object.keys(allDomains).sort();
      if (domains.length > 0) selectDomain(domains[0]);
    }
  } catch (err) {
    console.error('Failed to load entities:', err);
    setStatus(false, 'Failed to connect');
    document.getElementById('loading').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <h3>Connection Error</h3>
        <p>Could not connect to Home Assistant. Check the add-on logs.</p>
      </div>`;
  }
}

// ─── Render Domain List ────────────────────────

function renderDomainList() {
  const list = document.getElementById('domain-list');
  const domains = Object.keys(allDomains).sort();
  const exposedCount = getExposedEntities().length;
  const totalCount = getAllEntitiesFlat().length;

  let html = '';

  html += `
    <div class="domain-item ${activeDomain === '__exposed__' ? 'active' : ''}"
         onclick="selectDomain('__exposed__')" data-domain="__exposed__"
         style="border-bottom: 1px solid var(--border); margin-bottom: 4px; padding-bottom: 12px;">
      <span class="domain-icon">⭐</span>
      <span class="domain-name" style="font-weight:600;">Exposed</span>
      <span class="domain-count" style="background:var(--success-dim); color:var(--success);">${exposedCount}</span>
    </div>`;

  html += `
    <div class="domain-item ${activeDomain === '__all__' ? 'active' : ''}"
         onclick="selectDomain('__all__')" data-domain="__all__"
         style="border-bottom: 1px solid var(--border); margin-bottom: 4px; padding-bottom: 12px;">
      <span class="domain-icon">🌐</span>
      <span class="domain-name" style="font-weight:600;">All</span>
      <span class="domain-count">${totalCount}</span>
    </div>`;

  html += domains.map(domain => {
    const count = allDomains[domain].length;
    const selectedCount = allDomains[domain].filter(e => exposedEntities[e.entity_id]).length;
    const icon = DOMAIN_ICONS[domain] || '📦';
    const isActive = domain === activeDomain ? 'active' : '';
    return `
      <div class="domain-item ${isActive}" onclick="selectDomain('${domain}')" data-domain="${domain}">
        <span class="domain-icon">${icon}</span>
        <span class="domain-name">${domain}</span>
        <span class="domain-count">${selectedCount ? selectedCount + '/' : ''}${count}</span>
      </div>`;
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
}

// ─── Render Entity List (three-state toggle) ───

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
  } else if (activeDomain && allDomains[activeDomain]) {
    entities = allDomains[activeDomain];
  } else {
    entities = [];
  }

  if (entities.length === 0) {
    const emptyMsg = searchTerm ? 'No matching entities.' : activeDomain === '__exposed__' ? 'No entities exposed yet.' : 'No entities in this domain.';
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">${searchTerm ? '🔍' : '📡'}</div><h3>${searchTerm ? 'No results' : 'No entities'}</h3><p>${emptyMsg}</p></div>`;
    updateFilterStatus(0, 0);
    return;
  }

  list.innerHTML = entities.map(entity => {
    const access = exposedEntities[entity.entity_id] || null;
    const accessClass = access === 'control' ? 'control' : access === 'read' ? 'read' : '';
    const isSensitive = SENSITIVE_DOMAINS.includes(entity.domain);
    const domainBadge = (searchTerm || activeDomain === '__exposed__' || activeDomain === '__all__')
      ? `<span style="color:var(--text-3); font-size:10px; margin-left:6px; background:var(--bg-4); padding:1px 6px; border-radius:3px; font-family:var(--mono);">${entity.domain}</span>`
      : '';
    const sensitiveIcon = isSensitive && access === 'control' ? '<span class="sensitive-badge" title="Sensitive domain">⚠️</span>' : '';

    return `
      <div class="entity-card ${accessClass}" data-entity="${entity.entity_id}">
        <div class="entity-access-toggle" onclick="event.stopPropagation()">
          <button class="access-btn ${access === null ? 'active' : ''}" onclick="setEntityAccess('${entity.entity_id}', null)" title="Not exposed">off</button>
          <button class="access-btn read ${access === 'read' ? 'active' : ''}" onclick="setEntityAccess('${entity.entity_id}', 'read')" title="Read-only: AI can see state">read</button>
          <button class="access-btn control ${access === 'control' ? 'active' : ''}" onclick="setEntityAccess('${entity.entity_id}', 'control')" title="Control: AI can see + call services">ctrl</button>
        </div>
        <div class="entity-info">
          <div class="entity-name">${escapeHtml(entity.friendly_name)}${domainBadge}${sensitiveIcon}</div>
          <div class="entity-id">${entity.entity_id}</div>
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

  // Sensitive domain warning when granting control
  if (access === 'control' && SENSITIVE_DOMAINS.includes(domain)) {
    pendingSensitiveCallback = () => {
      _applyAccess(entityId, access);
    };
    document.getElementById('sensitive-modal-text').textContent =
      `You are about to grant AI control over "${entityId}". This allows OpenClaw to call services (turn on/off, lock/unlock, etc.) on this device.`;
    document.getElementById('sensitive-confirm-check').checked = false;
    document.getElementById('sensitive-confirm-btn').disabled = true;
    document.getElementById('sensitive-modal').classList.add('show');
    return;
  }

  _applyAccess(entityId, access);
}

function _applyAccess(entityId, access) {
  if (access === null) {
    delete exposedEntities[entityId];
  } else {
    exposedEntities[entityId] = access;
  }
  renderEntityList();
  renderDomainList();
  updateExposedCount();
  scheduleAutoSave();
}

function confirmSensitiveModal() {
  document.getElementById('sensitive-modal').classList.remove('show');
  if (pendingSensitiveCallback) {
    pendingSensitiveCallback();
    pendingSensitiveCallback = null;
  }
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
    } catch (err) {
      console.error('Auto-save failed:', err);
    }
  }, 500);
}

// ─── Undo ───────────────────────────────────────

function pushUndo() { undoSnapshot = { ...exposedEntities }; }

function undo() {
  if (!undoSnapshot) return;
  exposedEntities = { ...undoSnapshot };
  undoSnapshot = null;
  renderEntityList();
  renderDomainList();
  updateExposedCount();
  scheduleAutoSave();
  showToast(`Restored! ${Object.keys(exposedEntities).length} entities exposed.`);
}

// ─── Select / Deselect All ─────────────────────

function selectAllVisible(access) {
  const entities = getVisibleEntities();
  if (entities.length === 0) return;
  pushUndo();
  entities.forEach(e => { exposedEntities[e.entity_id] = access; });
  renderEntityList();
  renderDomainList();
  updateExposedCount();
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
  renderEntityList();
  renderDomainList();
  updateExposedCount();
  scheduleAutoSave();
  showUndoToast(`Removed ${entities.length} entities.`);
}

function getVisibleEntities() {
  const searchTerm = document.getElementById('search-input').value.toLowerCase();
  if (searchTerm) {
    return getAllEntitiesFlat().filter(e =>
      e.friendly_name.toLowerCase().includes(searchTerm) || e.entity_id.toLowerCase().includes(searchTerm)
    );
  } else if (activeDomain === '__exposed__') {
    return getExposedEntities();
  } else if (activeDomain === '__all__') {
    return getAllEntitiesFlat();
  } else if (activeDomain && allDomains[activeDomain]) {
    return allDomains[activeDomain];
  }
  return [];
}

// ─── Save Selection ────────────────────────────

async function saveSelection() {
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:14px;height:14px;border-width:2px;"></div> Saving...';
  try {
    await apiPost('/api/selection', { exposed_entities: exposedEntities });
    showToast(`Saved! ${Object.keys(exposedEntities).length} entities (${countByAccess('read')} read, ${countByAccess('control')} control).`);
  } catch (err) {
    showToast('Failed to save.', true);
    console.error(err);
  }
  btn.disabled = false;
  btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> Save`;
}

function filterEntities() { renderEntityList(); }

// ─── Tabs ──────────────────────────────────────

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.getElementById('tab-entities').style.display = tab === 'entities' ? '' : 'none';
  document.getElementById('tab-audit').style.display = tab === 'audit' ? '' : 'none';
  document.getElementById('tab-presets').style.display = tab === 'presets' ? '' : 'none';
  document.getElementById('tab-settings').style.display = tab === 'settings' ? '' : 'none';
  if (tab === 'presets') loadPresets();
  if (tab === 'audit') loadAuditLogs();
}

// ─── Audit ─────────────────────────────────────

async function loadAuditLogs() {
  const listEl = document.getElementById('audit-list');
  try {
    const data = await apiGet('/api/audit/logs?limit=200');
    const logs = data.logs || [];
    if (logs.length === 0) {
      listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><h3>No audit logs</h3><p>Service calls from OpenClaw will appear here.</p></div>`;
      return;
    }
    listEl.innerHTML = `<table class="audit-table">
      <thead><tr><th>Time</th><th>Entity</th><th>Service</th><th>Result</th><th>IP</th></tr></thead>
      <tbody>${logs.map(l => {
        const ts = l.timestamp ? new Date(l.timestamp).toLocaleString() : '-';
        const resultClass = l.result === 'success' ? 'audit-success' : l.result === 'denied' ? 'audit-denied' : 'audit-error';
        return `<tr>
          <td>${escapeHtml(ts)}</td>
          <td>${escapeHtml(l.entity_id || '-')}</td>
          <td>${escapeHtml((l.domain || '') + '.' + (l.service || ''))}</td>
          <td><span class="${resultClass}">${escapeHtml(l.result || '-')}</span></td>
          <td>${escapeHtml(l.source_ip || '-')}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  } catch (err) {
    console.error('Failed to load audit logs:', err);
    listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Error</h3><p>Could not load audit logs.</p></div>`;
  }
}

async function clearAuditLogs() {
  if (!confirm('Clear all audit logs?')) return;
  try {
    await apiDelete('/api/audit/logs');
    showToast('Audit log cleared.');
    loadAuditLogs();
  } catch (err) {
    showToast('Failed to clear audit log.', true);
  }
}

// ─── Presets ───────────────────────────────────

async function loadPresets() {
  try {
    const data = await apiGet('/api/presets');
    renderPresets(data.presets || {});
  } catch (err) {
    console.error('Failed to load presets:', err);
  }
}

function renderPresets(presets) {
  const list = document.getElementById('preset-list');
  const entries = Object.entries(presets);
  if (entries.length === 0) {
    list.innerHTML = `<div class="empty-state" style="padding:60px 40px;"><div class="empty-icon">📋</div><h3>No presets saved</h3><p>Select some entities and save them as a preset.</p></div>`;
    return;
  }
  list.innerHTML = entries.map(([name, data]) => {
    const count = typeof data === 'object' && !Array.isArray(data) ? Object.keys(data).length : (Array.isArray(data) ? data.length : 0);
    return `<div class="preset-item">
      <div>
        <span class="preset-name">${escapeHtml(name)}</span>
        <span class="preset-count">${count} entities</span>
      </div>
      <div class="preset-actions">
        <button class="btn btn-sm btn-primary" onclick="applyPreset('${escapeAttr(name)}')">Load</button>
        <button class="btn btn-sm btn-danger" onclick="deletePreset('${escapeAttr(name)}')">Delete</button>
      </div>
    </div>`;
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
  try {
    await apiPost('/api/presets', { name, entities: exposedEntities });
    showToast(`Preset "${name}" saved.`);
    hidePresetModal();
    loadPresets();
  } catch (err) {
    showToast('Failed to save preset.', true);
  }
}

async function applyPreset(name) {
  try {
    const data = await apiGet(`/api/presets/${encodeURIComponent(name)}`);
    const entities = data.entities || {};
    if (typeof entities === 'object' && !Array.isArray(entities)) {
      exposedEntities = entities;
    } else if (Array.isArray(entities)) {
      exposedEntities = {};
      entities.forEach(eid => { exposedEntities[eid] = 'read'; });
    }
    renderEntityList();
    renderDomainList();
    updateExposedCount();
    scheduleAutoSave();
    showToast(`Loaded preset "${name}".`);
    switchTab('entities');
  } catch (err) {
    showToast('Failed to load preset.', true);
  }
}

async function deletePreset(name) {
  if (!confirm(`Delete preset "${name}"?`)) return;
  try {
    await apiDelete(`/api/presets/${encodeURIComponent(name)}`);
    showToast(`Preset "${name}" deleted.`);
    loadPresets();
  } catch (err) {
    showToast('Failed to delete preset.', true);
  }
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
  } catch (err) {
    console.error('Failed to load settings:', err);
  }
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
  };
  try {
    await apiPost('/api/settings', settings);
    showToast('Settings saved.');
  } catch (err) {
    showToast('Failed to save settings.', true);
  }
}

// ─── Export / Import ───────────────────────────

async function exportConfig() {
  try {
    const data = await apiGet('/api/config/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'clawbridge_config.json'; a.click();
    URL.revokeObjectURL(url);
    showToast('Configuration exported.');
  } catch (err) {
    showToast('Failed to export config.', true);
  }
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
    } catch (err) {
      showToast('Failed to import config.', true);
    }
  };
  reader.readAsText(file);
  event.target.value = '';
}

// ─── UI Helpers ────────────────────────────────

function updateExposedCount() {
  const total = Object.keys(exposedEntities).length;
  const readCount = countByAccess('read');
  const controlCount = countByAccess('control');
  document.getElementById('exposed-count').textContent = total;
  document.getElementById('read-count').textContent = readCount;
  document.getElementById('control-count').textContent = controlCount;
}

function updateFilterStatus(total, selected) {
  document.getElementById('status-filter').textContent = `Showing ${total} entities, ${selected} selected`;
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
