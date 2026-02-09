/* ═══════════════════════════════════════════════
   AI Sensor Exporter - Frontend Application
   ═══════════════════════════════════════════════ */

const BASE_PATH = document.querySelector('link[rel="stylesheet"]').href.replace('/static/style.css', '');

// ─── State ─────────────────────────────────────
let allDomains = {};
let selectedEntities = new Set();
let activeDomain = null;
let currentTab = 'entities';

// Domain icons (mdi-style emoji fallbacks)
const DOMAIN_ICONS = {
  sensor: '📊',
  binary_sensor: '🔘',
  light: '💡',
  switch: '🔌',
  climate: '🌡️',
  cover: '🪟',
  fan: '🌀',
  lock: '🔒',
  media_player: '🎵',
  camera: '📷',
  vacuum: '🤖',
  weather: '🌤️',
  person: '👤',
  device_tracker: '📍',
  automation: '⚙️',
  script: '📜',
  scene: '🎬',
  input_boolean: '☑️',
  input_number: '🔢',
  input_select: '📋',
  input_text: '📝',
  timer: '⏱️',
  counter: '🔄',
  alert: '🚨',
  group: '📁',
  zone: '🗺️',
  sun: '☀️',
  water_heater: '🚿',
  humidifier: '💧',
  number: '🔢',
  select: '📋',
  button: '🔘',
  text: '📝',
  update: '🔄',
  remote: '📺',
  siren: '🔔',
  calendar: '📅',
  tts: '🗣️',
  image: '🖼️',
  stt: '🎤',
  conversation: '💬',
  todo: '✅',
  event: '📢',
  valve: '🔧',
  lawn_mower: '🌱',
  notify: '📣',
  tag: '🏷️',
  schedule: '📅',
  date: '📆',
  time: '🕐',
  datetime: '📅',
  wake_word: '🎤',
};

// ─── Init ──────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadEntities();
  loadSettings();
});

// ─── API Helpers ───────────────────────────────

async function apiGet(path) {
  const resp = await fetch(`${BASE_PATH}${path}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

async function apiPost(path, data) {
  const resp = await fetch(`${BASE_PATH}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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

// ─── Load Entities ─────────────────────────────

async function loadEntities() {
  try {
    const data = await apiGet('/api/entities');
    allDomains = data.domains;
    selectedEntities = new Set(data.selected || []);
    renderDomainList();
    updateExposedCount();
    setStatus(true, `${Object.values(allDomains).flat().length} entities loaded`);

    // Auto-select first domain
    const domains = Object.keys(allDomains).sort();
    if (domains.length > 0) {
      selectDomain(domains[0]);
    } else {
      document.getElementById('loading').innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📡</div>
          <h3>No entities found</h3>
          <p>Make sure Home Assistant is running and the add-on has API access.</p>
        </div>`;
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

  list.innerHTML = domains.map(domain => {
    const count = allDomains[domain].length;
    const selectedCount = allDomains[domain].filter(e => selectedEntities.has(e.entity_id)).length;
    const icon = DOMAIN_ICONS[domain] || '📦';
    const isActive = domain === activeDomain ? 'active' : '';

    return `
      <div class="domain-item ${isActive}" onclick="selectDomain('${domain}')" data-domain="${domain}">
        <span class="domain-icon">${icon}</span>
        <span class="domain-name">${domain}</span>
        <span class="domain-count">${selectedCount ? selectedCount + '/' : ''}${count}</span>
      </div>`;
  }).join('');
}

// ─── Select Domain ─────────────────────────────

function selectDomain(domain) {
  activeDomain = domain;

  // Update sidebar active state
  document.querySelectorAll('.domain-item').forEach(el => {
    el.classList.toggle('active', el.dataset.domain === domain);
  });

  document.getElementById('status-domain').textContent = `${DOMAIN_ICONS[domain] || '📦'} ${domain}`;
  renderEntityList();
}

// ─── Render Entity List ────────────────────────

function renderEntityList() {
  if (!activeDomain || !allDomains[activeDomain]) return;

  const list = document.getElementById('entity-list');
  const searchTerm = document.getElementById('search-input').value.toLowerCase();
  let entities = allDomains[activeDomain];

  // Filter by search
  if (searchTerm) {
    entities = entities.filter(e =>
      e.friendly_name.toLowerCase().includes(searchTerm) ||
      e.entity_id.toLowerCase().includes(searchTerm)
    );
  }

  if (entities.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <h3>No matching entities</h3>
        <p>Try a different search term or select another domain.</p>
      </div>`;
    updateFilterStatus(0, 0);
    return;
  }

  list.innerHTML = entities.map(entity => {
    const isSelected = selectedEntities.has(entity.entity_id);
    const stateClass = entity.device_class ? entity.device_class : '';

    return `
      <div class="entity-card ${isSelected ? 'selected' : ''}"
           onclick="toggleEntity('${entity.entity_id}')"
           data-entity="${entity.entity_id}">
        <div class="entity-checkbox">
          <svg viewBox="0 0 24 24" fill="none" stroke="#1a1a2e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
        <div class="entity-info">
          <div class="entity-name">${escapeHtml(entity.friendly_name)}</div>
          <div class="entity-id">${entity.entity_id}</div>
        </div>
        <div class="entity-state">
          <span class="state-value">${escapeHtml(entity.state)}</span>
          ${entity.unit_of_measurement ? `<span class="state-unit">${escapeHtml(entity.unit_of_measurement)}</span>` : ''}
          ${stateClass ? `<span class="state-class">${escapeHtml(stateClass)}</span>` : ''}
        </div>
      </div>`;
  }).join('');

  const selectedInDomain = entities.filter(e => selectedEntities.has(e.entity_id)).length;
  updateFilterStatus(entities.length, selectedInDomain);
}

// ─── Toggle Entity ─────────────────────────────

function toggleEntity(entityId) {
  if (selectedEntities.has(entityId)) {
    selectedEntities.delete(entityId);
  } else {
    selectedEntities.add(entityId);
  }

  // Update card style without full re-render
  const card = document.querySelector(`[data-entity="${entityId}"]`);
  if (card) {
    card.classList.toggle('selected', selectedEntities.has(entityId));
  }

  updateExposedCount();
  renderDomainList();
}

// ─── Select / Deselect All ─────────────────────

function selectAllVisible() {
  if (!activeDomain) return;
  const searchTerm = document.getElementById('search-input').value.toLowerCase();
  let entities = allDomains[activeDomain];
  if (searchTerm) {
    entities = entities.filter(e =>
      e.friendly_name.toLowerCase().includes(searchTerm) ||
      e.entity_id.toLowerCase().includes(searchTerm)
    );
  }
  entities.forEach(e => selectedEntities.add(e.entity_id));
  renderEntityList();
  renderDomainList();
  updateExposedCount();
}

function deselectAllVisible() {
  if (!activeDomain) return;
  const searchTerm = document.getElementById('search-input').value.toLowerCase();
  let entities = allDomains[activeDomain];
  if (searchTerm) {
    entities = entities.filter(e =>
      e.friendly_name.toLowerCase().includes(searchTerm) ||
      e.entity_id.toLowerCase().includes(searchTerm)
    );
  }
  entities.forEach(e => selectedEntities.delete(e.entity_id));
  renderEntityList();
  renderDomainList();
  updateExposedCount();
}

// ─── Save Selection ────────────────────────────

async function saveSelection() {
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:14px;height:14px;border-width:2px;"></div> Saving...';

  try {
    await apiPost('/api/selection', { entities: Array.from(selectedEntities) });
    showToast(`Saved! ${selectedEntities.size} entities exposed.`);
  } catch (err) {
    showToast('Failed to save configuration.', true);
    console.error(err);
  }

  btn.disabled = false;
  btn.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
    Save Configuration`;
}

// ─── Search / Filter ───────────────────────────

function filterEntities() {
  renderEntityList();
}

// ─── Tabs ──────────────────────────────────────

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.getElementById('tab-entities').style.display = tab === 'entities' ? '' : 'none';
  document.getElementById('tab-presets').style.display = tab === 'presets' ? '' : 'none';
  document.getElementById('tab-settings').style.display = tab === 'settings' ? '' : 'none';

  if (tab === 'presets') loadPresets();
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
    list.innerHTML = `
      <div class="empty-state" style="padding:60px 40px;">
        <div class="empty-icon">📋</div>
        <h3>No presets saved</h3>
        <p>Select some entities and save them as a preset for quick loading later.</p>
      </div>`;
    return;
  }

  list.innerHTML = entries.map(([name, entities]) => `
    <div class="preset-item">
      <div>
        <span class="preset-name">${escapeHtml(name)}</span>
        <span class="preset-count">${entities.length} entities</span>
      </div>
      <div class="preset-actions">
        <button class="btn btn-sm btn-primary" onclick="applyPreset('${escapeAttr(name)}')">Load</button>
        <button class="btn btn-sm btn-danger" onclick="deletePreset('${escapeAttr(name)}')">Delete</button>
      </div>
    </div>`).join('');
}

function showSavePresetModal() {
  document.getElementById('preset-modal').classList.add('show');
  document.getElementById('preset-name-input').value = '';
  document.getElementById('preset-name-input').focus();
}

function hidePresetModal() {
  document.getElementById('preset-modal').classList.remove('show');
}

async function savePreset() {
  const name = document.getElementById('preset-name-input').value.trim();
  if (!name) return;

  try {
    await apiPost('/api/presets', { name, entities: Array.from(selectedEntities) });
    showToast(`Preset "${name}" saved with ${selectedEntities.size} entities.`);
    hidePresetModal();
    loadPresets();
  } catch (err) {
    showToast('Failed to save preset.', true);
  }
}

async function applyPreset(name) {
  try {
    const data = await apiGet(`/api/presets/${encodeURIComponent(name)}`);
    selectedEntities = new Set(data.entities || []);
    renderEntityList();
    renderDomainList();
    updateExposedCount();
    showToast(`Loaded preset "${name}" with ${selectedEntities.size} entities.`);
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
  } catch (err) {
    console.error('Failed to load settings:', err);
  }
}

async function saveSettings() {
  const settings = {
    refresh_interval: parseInt(document.getElementById('setting-refresh').value, 10),
    filter_unavailable: document.getElementById('setting-filter-unavailable').checked,
    compact_mode: document.getElementById('setting-compact').checked,
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
    a.href = url;
    a.download = 'ai_sensor_exporter_config.json';
    a.click();
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
  document.getElementById('exposed-count').textContent = selectedEntities.size;
}

function updateFilterStatus(total, selected) {
  document.getElementById('status-filter').textContent = `Showing ${total} entities, ${selected} selected`;
}

function setStatus(connected, text) {
  const dot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  dot.classList.toggle('disconnected', !connected);
  statusText.textContent = text;
}

function showToast(message, isError = false) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => toast.classList.remove('show'), 3000);
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
