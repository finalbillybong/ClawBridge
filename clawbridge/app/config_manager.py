"""Configuration manager for ClawBridge.

Handles persistence of selected entities, presets, and settings.
Stores config in /data/ directory (mapped via addon_config).
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

CONFIG_DIR = "/data"
CONFIG_FILE = os.path.join(CONFIG_DIR, "ai_sensor_exporter.json")

DEFAULT_CONFIG = {
    # Unified entity model: { entity_id: "read"|"control" }
    "exposed_entities": {},
    "presets": {},
    "refresh_interval": 5,
    "filter_unavailable": True,
    "compact_mode": False,
    # Security
    "audit_enabled": True,
    "audit_retention_days": 30,
    "rate_limit_per_minute": 60,
    "allowed_ips": [],
}


class ConfigManager:
    def __init__(self):
        self._config = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        """Load configuration from disk and migrate old format if needed."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                self._config.update(data)
                logger.info("Configuration loaded")
            except Exception as e:
                logger.error("Failed to load config: %s", e)
        else:
            logger.info("No existing config found, using defaults")

        # Migrate from old format (selected_entities list + exposed_actions dict)
        self._migrate_old_format()

    def _migrate_old_format(self):
        """Convert old selected_entities list + exposed_actions to unified exposed_entities dict."""
        old_selected = self._config.get("selected_entities")
        old_actions = self._config.get("exposed_actions")
        exposed = self._config.get("exposed_entities", {})

        if not isinstance(exposed, dict):
            exposed = {}

        migrated = False

        # Migrate old selected_entities (list) -> exposed_entities with "read" access
        if isinstance(old_selected, list) and old_selected:
            for eid in old_selected:
                if isinstance(eid, str) and eid and eid not in exposed:
                    exposed[eid] = "read"
            self._config.pop("selected_entities", None)
            migrated = True
            logger.info("Migrated %d old selected_entities to read access", len(old_selected))

        # Promote entities from old exposed_actions to "control" access
        if isinstance(old_actions, dict) and old_actions:
            for service_id, entity_ids in old_actions.items():
                if isinstance(entity_ids, list):
                    for eid in entity_ids:
                        if isinstance(eid, str) and eid:
                            exposed[eid] = "control"
            self._config.pop("exposed_actions", None)
            migrated = True
            logger.info("Migrated old exposed_actions -> promoted entities to control access")

        if migrated:
            self._config["exposed_entities"] = exposed
            self._save()
            logger.info("Migration complete: %d entities (%d read, %d control)",
                        len(exposed),
                        sum(1 for v in exposed.values() if v == "read"),
                        sum(1 for v in exposed.values() if v == "control"))

    def _save(self):
        """Persist configuration to disk."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._config, f, indent=2)
            logger.debug("Configuration saved")
        except Exception as e:
            logger.error("Failed to save config: %s", e)

    # ── Exposed Entities (unified model) ──────────

    @property
    def exposed_entities(self):
        """Dict of entity_id -> 'read'|'control'."""
        return self._config.get("exposed_entities", {})

    @exposed_entities.setter
    def exposed_entities(self, value):
        if not isinstance(value, dict):
            value = {}
        self._config["exposed_entities"] = {
            k: v if v in ("read", "control") else "read"
            for k, v in value.items()
            if isinstance(k, str) and k
        }
        self._save()

    def get_all_exposed_ids(self):
        """Return list of all exposed entity IDs (both read + control)."""
        return list(self.exposed_entities.keys())

    def get_read_entity_ids(self):
        """Return list of entity IDs with read-only access."""
        return [eid for eid, access in self.exposed_entities.items() if access == "read"]

    def get_control_entity_ids(self):
        """Return list of entity IDs with control access."""
        return [eid for eid, access in self.exposed_entities.items() if access == "control"]

    def is_entity_exposed(self, entity_id):
        """Check if entity is exposed. Returns 'read', 'control', or False."""
        return self.exposed_entities.get(entity_id, False)

    def get_control_domains(self):
        """Return set of domains that have at least one entity with control access."""
        domains = set()
        for eid, access in self.exposed_entities.items():
            if access == "control" and "." in eid:
                domains.add(eid.split(".")[0])
        return domains

    # ── Backward-compatible selected_entities property ──

    @property
    def selected_entities(self):
        """Backward compat: return all exposed entity IDs as a list."""
        return self.get_all_exposed_ids()

    @selected_entities.setter
    def selected_entities(self, entities):
        """Backward compat: set entities (preserves existing access levels)."""
        old = self.exposed_entities
        new_exposed = {}
        for eid in entities:
            if isinstance(eid, str) and eid:
                new_exposed[eid] = old.get(eid, "read")
        self._config["exposed_entities"] = new_exposed
        self._save()

    # ── Presets ────────────────────────────────────

    @property
    def presets(self):
        return self._config.get("presets", {})

    def save_preset(self, name, entities):
        """Save a named preset (stores the full exposed_entities dict)."""
        if "presets" not in self._config:
            self._config["presets"] = {}
        # Accept both list (legacy) and dict (new format)
        if isinstance(entities, dict):
            self._config["presets"][name] = entities
        else:
            # Legacy list format: snapshot current access levels
            current = self.exposed_entities
            self._config["presets"][name] = {
                eid: current.get(eid, "read") for eid in entities if isinstance(eid, str)
            }
        self._save()

    def load_preset(self, name):
        """Load a named preset. Returns dict or list (legacy) or None."""
        return self._config.get("presets", {}).get(name)

    def delete_preset(self, name):
        """Delete a named preset."""
        if name in self._config.get("presets", {}):
            del self._config["presets"][name]
            self._save()
            return True
        return False

    # ── Settings ──────────────────────────────────

    @property
    def refresh_interval(self):
        return self._config.get("refresh_interval", 5)

    @refresh_interval.setter
    def refresh_interval(self, value):
        self._config["refresh_interval"] = max(1, min(3600, int(value)))
        self._save()

    @property
    def filter_unavailable(self):
        return self._config.get("filter_unavailable", True)

    @filter_unavailable.setter
    def filter_unavailable(self, value):
        self._config["filter_unavailable"] = bool(value)
        self._save()

    @property
    def compact_mode(self):
        return self._config.get("compact_mode", False)

    @compact_mode.setter
    def compact_mode(self, value):
        self._config["compact_mode"] = bool(value)
        self._save()

    # ── Security settings ─────────────────────────

    @property
    def audit_enabled(self):
        return self._config.get("audit_enabled", True)

    @audit_enabled.setter
    def audit_enabled(self, value):
        self._config["audit_enabled"] = bool(value)
        self._save()

    @property
    def audit_retention_days(self):
        return self._config.get("audit_retention_days", 30)

    @audit_retention_days.setter
    def audit_retention_days(self, value):
        self._config["audit_retention_days"] = max(1, min(365, int(value)))
        self._save()

    @property
    def rate_limit_per_minute(self):
        return self._config.get("rate_limit_per_minute", 60)

    @rate_limit_per_minute.setter
    def rate_limit_per_minute(self, value):
        self._config["rate_limit_per_minute"] = max(1, min(600, int(value)))
        self._save()

    @property
    def allowed_ips(self):
        return self._config.get("allowed_ips", [])

    @allowed_ips.setter
    def allowed_ips(self, value):
        if not isinstance(value, list):
            value = []
        self._config["allowed_ips"] = [ip for ip in value if isinstance(ip, str) and ip.strip()]
        self._save()

    # ── Export / Import ───────────────────────────

    def export_config(self):
        """Export full config as dict for backup."""
        return dict(self._config)

    def import_config(self, data):
        """Import config from dict."""
        self._config.update(data)
        self._save()
