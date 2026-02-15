"""Configuration manager for ClawBridge.

Handles persistence of exposed entities, presets, settings, annotations,
constraints, API keys, schedules, and confirmation settings.
Stores config in /data/ directory (mapped via addon_config).
"""

import json
import os
import logging
import secrets
import string
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CONFIG_DIR = "/data"
CONFIG_FILE = os.path.join(CONFIG_DIR, "ai_sensor_exporter.json")

VALID_ACCESS_LEVELS = ("read", "confirm", "control")

DEFAULT_CONFIG = {
    # Unified entity model: { entity_id: "read"|"confirm"|"control" }
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
    # Annotations: { entity_id: "description string" }
    "entity_annotations": {},
    # Constraints: { entity_id: { param_name: { "min": X, "max": Y } } }
    "entity_constraints": {},
    # API keys: { key_id: { "name": str, "key": str, "entities": {eid: level}, "rate_limit": int, "created": ISO } }
    "api_keys": {},
    # Schedules: { schedule_id: { "name": str, "start": "HH:MM", "end": "HH:MM", "days": [0-6], "timezone": "auto" } }
    "schedules": {},
    # Entity-to-schedule mapping: { entity_id: schedule_id }
    "entity_schedules": {},
    # Confirmation settings
    "confirm_timeout_seconds": 120,
    "confirm_notify_service": "",
    # AI display name for notifications
    "ai_name": "AI",
    # Chat / AI Gateway
    "gateway_url": "",
    "gateway_token": "",
    "chat_history": [],
    # Chat notifications
    "chat_notify_enabled": False,
    "chat_notify_service": "",       # empty = fall back to confirm_notify_service
    "chat_notify_max_length": 500,
    # Entity groups: { group_id: { "name": str, "entities": [entity_id, ...], "icon": str } }
    "entity_groups": {},
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
                # Ensure defaults for any new keys
                for key, default_val in DEFAULT_CONFIG.items():
                    if key not in data:
                        data[key] = default_val
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
        """Dict of entity_id -> 'read'|'confirm'|'control'."""
        return self._config.get("exposed_entities", {})

    @exposed_entities.setter
    def exposed_entities(self, value):
        if not isinstance(value, dict):
            value = {}
        self._config["exposed_entities"] = {
            k: v if v in VALID_ACCESS_LEVELS else "read"
            for k, v in value.items()
            if isinstance(k, str) and k
        }
        self._save()

    def get_all_exposed_ids(self):
        """Return list of all exposed entity IDs (read + confirm + control)."""
        return list(self.exposed_entities.keys())

    def get_read_entity_ids(self):
        """Return list of entity IDs with read-only access."""
        return [eid for eid, access in self.exposed_entities.items() if access == "read"]

    def get_confirm_entity_ids(self):
        """Return list of entity IDs with confirm access."""
        return [eid for eid, access in self.exposed_entities.items() if access == "confirm"]

    def get_control_entity_ids(self):
        """Return list of entity IDs with control access."""
        return [eid for eid, access in self.exposed_entities.items() if access == "control"]

    def get_actionable_entity_ids(self):
        """Return list of entity IDs with confirm or control access (can call services)."""
        return [eid for eid, access in self.exposed_entities.items() if access in ("confirm", "control")]

    def is_entity_exposed(self, entity_id):
        """Check if entity is exposed. Returns 'read', 'confirm', 'control', or False."""
        return self.exposed_entities.get(entity_id, False)

    def get_control_domains(self):
        """Return set of domains that have at least one entity with control or confirm access."""
        domains = set()
        for eid, access in self.exposed_entities.items():
            if access in ("control", "confirm") and "." in eid:
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

    # ── Annotations ───────────────────────────────

    @property
    def entity_annotations(self):
        """Dict of entity_id -> description string."""
        return self._config.get("entity_annotations", {})

    @entity_annotations.setter
    def entity_annotations(self, value):
        if not isinstance(value, dict):
            value = {}
        self._config["entity_annotations"] = {
            k: str(v)[:500] for k, v in value.items()
            if isinstance(k, str) and k and v
        }
        self._save()

    def get_annotation(self, entity_id):
        """Get annotation for an entity, or None."""
        return self.entity_annotations.get(entity_id)

    def set_annotation(self, entity_id, text):
        """Set or remove annotation for an entity."""
        annotations = self._config.get("entity_annotations", {})
        if text and text.strip():
            annotations[entity_id] = str(text).strip()[:500]
        else:
            annotations.pop(entity_id, None)
        self._config["entity_annotations"] = annotations
        self._save()

    # ── Constraints ───────────────────────────────

    @property
    def entity_constraints(self):
        """Dict of entity_id -> { param_name: { min, max } }."""
        return self._config.get("entity_constraints", {})

    @entity_constraints.setter
    def entity_constraints(self, value):
        if not isinstance(value, dict):
            value = {}
        self._config["entity_constraints"] = value
        self._save()

    def get_constraints(self, entity_id):
        """Get constraints for an entity, or empty dict."""
        return self.entity_constraints.get(entity_id, {})

    def set_constraints(self, entity_id, constraints):
        """Set or remove constraints for an entity."""
        all_constraints = self._config.get("entity_constraints", {})
        if constraints:
            all_constraints[entity_id] = constraints
        else:
            all_constraints.pop(entity_id, None)
        self._config["entity_constraints"] = all_constraints
        self._save()

    def validate_parameters(self, entity_id, params):
        """Validate and clamp parameters against constraints.
        Returns (clamped_params, violations_list).
        violations_list: [{ param, value, min, max, clamped_to }]
        """
        constraints = self.get_constraints(entity_id)
        if not constraints or not params:
            return params, []

        clamped = dict(params)
        violations = []
        for param, limits in constraints.items():
            if param not in clamped:
                continue
            val = clamped[param]
            if not isinstance(val, (int, float)):
                continue
            min_val = limits.get("min")
            max_val = limits.get("max")
            original = val
            if min_val is not None and val < min_val:
                val = min_val
            if max_val is not None and val > max_val:
                val = max_val
            if val != original:
                clamped[param] = val
                violations.append({
                    "param": param, "value": original,
                    "min": min_val, "max": max_val, "clamped_to": val,
                })
        return clamped, violations

    # ── API Keys ──────────────────────────────────

    @property
    def api_keys(self):
        """Dict of key_id -> key config."""
        return self._config.get("api_keys", {})

    def create_api_key(self, name, entities=None, rate_limit=None):
        """Create a new API key. Returns (key_id, full_key)."""
        key_id = "cbk_" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
        full_key = "cb_" + secrets.token_urlsafe(32)
        keys = self._config.get("api_keys", {})
        keys[key_id] = {
            "name": str(name)[:100],
            "key": full_key,
            "entities": entities or {},  # empty = inherit global
            "rate_limit": rate_limit or 0,  # 0 = use global
            "created": datetime.now(timezone.utc).isoformat(),
        }
        self._config["api_keys"] = keys
        self._save()
        return key_id, full_key

    def delete_api_key(self, key_id):
        """Delete an API key. Returns True if found."""
        keys = self._config.get("api_keys", {})
        if key_id in keys:
            del keys[key_id]
            self._config["api_keys"] = keys
            self._save()
            return True
        return False

    def get_key_by_token(self, token):
        """Look up API key config by the bearer token. Returns (key_id, key_config) or (None, None)."""
        for key_id, key_config in self.api_keys.items():
            if key_config.get("key") == token:
                return key_id, key_config
        return None, None

    def list_api_keys(self):
        """Return list of API keys (with token masked)."""
        result = []
        for key_id, config in self.api_keys.items():
            result.append({
                "key_id": key_id,
                "name": config.get("name", ""),
                "entity_count": len(config.get("entities", {})),
                "rate_limit": config.get("rate_limit", 0),
                "created": config.get("created", ""),
                "key_preview": config.get("key", "")[:7] + "..." if config.get("key") else "",
            })
        return result

    # ── Schedules ─────────────────────────────────

    @property
    def schedules(self):
        """Dict of schedule_id -> schedule config."""
        return self._config.get("schedules", {})

    @property
    def entity_schedules(self):
        """Dict of entity_id -> schedule_id."""
        return self._config.get("entity_schedules", {})

    def create_schedule(self, name, start, end, days=None, timezone_str="auto"):
        """Create a named schedule. Returns schedule_id."""
        schedule_id = "sch_" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        schedules = self._config.get("schedules", {})
        schedules[schedule_id] = {
            "name": str(name)[:100],
            "start": start,  # "HH:MM"
            "end": end,      # "HH:MM"
            "days": days if days is not None else [0, 1, 2, 3, 4, 5, 6],  # 0=Mon..6=Sun
            "timezone": timezone_str,
        }
        self._config["schedules"] = schedules
        self._save()
        return schedule_id

    def delete_schedule(self, schedule_id):
        """Delete a schedule and unassign from all entities."""
        schedules = self._config.get("schedules", {})
        if schedule_id not in schedules:
            return False
        del schedules[schedule_id]
        # Remove from entity_schedules
        entity_schedules = self._config.get("entity_schedules", {})
        self._config["entity_schedules"] = {
            eid: sid for eid, sid in entity_schedules.items() if sid != schedule_id
        }
        self._config["schedules"] = schedules
        self._save()
        return True

    def update_schedule(self, schedule_id, **kwargs):
        """Update schedule fields."""
        schedules = self._config.get("schedules", {})
        if schedule_id not in schedules:
            return False
        for key in ("name", "start", "end", "days", "timezone"):
            if key in kwargs:
                schedules[schedule_id][key] = kwargs[key]
        self._config["schedules"] = schedules
        self._save()
        return True

    def set_entity_schedule(self, entity_id, schedule_id):
        """Assign a schedule to an entity. None to remove."""
        entity_schedules = self._config.get("entity_schedules", {})
        if schedule_id:
            entity_schedules[entity_id] = schedule_id
        else:
            entity_schedules.pop(entity_id, None)
        self._config["entity_schedules"] = entity_schedules
        self._save()

    def is_within_schedule(self, entity_id):
        """Check if current time is within the entity's schedule.
        Returns True if no schedule assigned or within allowed time.
        Returns False if outside schedule.
        """
        schedule_id = self.entity_schedules.get(entity_id)
        if not schedule_id:
            return True  # No schedule = always allowed
        schedule = self.schedules.get(schedule_id)
        if not schedule:
            return True  # Schedule deleted

        now = datetime.now()
        current_day = now.weekday()  # 0=Monday
        allowed_days = schedule.get("days", [0, 1, 2, 3, 4, 5, 6])
        if current_day not in allowed_days:
            return False

        try:
            start_h, start_m = map(int, schedule["start"].split(":"))
            end_h, end_m = map(int, schedule["end"].split(":"))
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            current_minutes = now.hour * 60 + now.minute

            if start_minutes <= end_minutes:
                return start_minutes <= current_minutes <= end_minutes
            else:
                # Wraps midnight (e.g., 22:00 - 06:00)
                return current_minutes >= start_minutes or current_minutes <= end_minutes
        except (ValueError, KeyError):
            return True  # Malformed schedule = allow

    # ── Confirmation settings ─────────────────────

    @property
    def confirm_timeout_seconds(self):
        return self._config.get("confirm_timeout_seconds", 120)

    @confirm_timeout_seconds.setter
    def confirm_timeout_seconds(self, value):
        self._config["confirm_timeout_seconds"] = max(10, min(600, int(value)))
        self._save()

    @property
    def confirm_notify_service(self):
        return self._config.get("confirm_notify_service", "")

    @confirm_notify_service.setter
    def confirm_notify_service(self, value):
        self._config["confirm_notify_service"] = str(value).strip()
        self._save()

    @property
    def ai_name(self):
        return self._config.get("ai_name", "AI")

    @ai_name.setter
    def ai_name(self, value):
        self._config["ai_name"] = str(value)[:50].strip() if value else "AI"
        self._save()

    # ── Chat / AI Gateway ─────────────────────────

    @property
    def gateway_url(self):
        return self._config.get("gateway_url", "")

    @gateway_url.setter
    def gateway_url(self, value):
        self._config["gateway_url"] = str(value).strip() if value else ""
        self._save()

    @property
    def gateway_token(self):
        return self._config.get("gateway_token", "")

    @gateway_token.setter
    def gateway_token(self, value):
        self._config["gateway_token"] = str(value).strip() if value else ""
        self._save()

    @property
    def chat_history(self):
        return self._config.get("chat_history", [])

    @chat_history.setter
    def chat_history(self, value):
        if not isinstance(value, list):
            value = []
        # Cap at 200 messages
        self._config["chat_history"] = value[-200:]
        self._save()

    # ── Chat Notifications ─────────────────────────

    @property
    def chat_notify_enabled(self):
        return self._config.get("chat_notify_enabled", False)

    @chat_notify_enabled.setter
    def chat_notify_enabled(self, value):
        self._config["chat_notify_enabled"] = bool(value)
        self._save()

    @property
    def chat_notify_service(self):
        return self._config.get("chat_notify_service", "")

    @chat_notify_service.setter
    def chat_notify_service(self, value):
        self._config["chat_notify_service"] = str(value).strip() if value else ""
        self._save()

    @property
    def chat_notify_max_length(self):
        return self._config.get("chat_notify_max_length", 500)

    @chat_notify_max_length.setter
    def chat_notify_max_length(self, value):
        self._config["chat_notify_max_length"] = max(50, min(2000, int(value)))
        self._save()

    # ── Entity Groups ──────────────────────────────

    @property
    def entity_groups(self):
        """Dict of group_id -> { name, entities, icon }."""
        return self._config.get("entity_groups", {})

    def create_group(self, name, entities=None, icon=""):
        """Create a new entity group. Returns group_id."""
        group_id = "grp_" + "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6)
        )
        groups = self._config.get("entity_groups", {})
        groups[group_id] = {
            "name": str(name)[:100],
            "entities": list(entities) if entities else [],
            "icon": str(icon)[:10] if icon else "",
        }
        self._config["entity_groups"] = groups
        self._save()
        return group_id

    def update_group(self, group_id, **kwargs):
        """Update group fields (name, entities, icon)."""
        groups = self._config.get("entity_groups", {})
        if group_id not in groups:
            return False
        for key in ("name", "entities", "icon"):
            if key in kwargs:
                if key == "name":
                    groups[group_id][key] = str(kwargs[key])[:100]
                elif key == "entities":
                    groups[group_id][key] = list(kwargs[key])
                elif key == "icon":
                    groups[group_id][key] = str(kwargs[key])[:10]
        self._config["entity_groups"] = groups
        self._save()
        return True

    def delete_group(self, group_id):
        """Delete an entity group. Returns True if found."""
        groups = self._config.get("entity_groups", {})
        if group_id in groups:
            del groups[group_id]
            self._config["entity_groups"] = groups
            self._save()
            return True
        return False

    def set_group_access_level(self, group_id, access_level):
        """Set all entities in a group to the given access level.
        Returns count of entities changed.
        """
        if access_level not in VALID_ACCESS_LEVELS and access_level != "off":
            return 0
        groups = self._config.get("entity_groups", {})
        group = groups.get(group_id)
        if not group:
            return 0

        exposed = self._config.get("exposed_entities", {})
        count = 0
        for eid in group.get("entities", []):
            if access_level == "off":
                if eid in exposed:
                    del exposed[eid]
                    count += 1
            else:
                exposed[eid] = access_level
                count += 1
        self._config["exposed_entities"] = exposed
        self._save()
        return count

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
