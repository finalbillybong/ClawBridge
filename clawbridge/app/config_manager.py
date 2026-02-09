"""Configuration manager for ClawBridge.

Handles persistence of selected entities and presets.
Stores config in /data/ directory (mapped via addon_config).
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

CONFIG_DIR = "/data"
CONFIG_FILE = os.path.join(CONFIG_DIR, "ai_sensor_exporter.json")

DEFAULT_CONFIG = {
    "selected_entities": [],
    "presets": {},
    "refresh_interval": 5,
    "filter_unavailable": True,
    "compact_mode": False,
}


class ConfigManager:
    def __init__(self):
        self._config = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        """Load configuration from disk."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                self._config.update(data)
                logger.info("Configuration loaded: %d entities selected", len(self._config.get("selected_entities", [])))
            except Exception as e:
                logger.error("Failed to load config: %s", e)
        else:
            logger.info("No existing config found, using defaults")

    def _save(self):
        """Persist configuration to disk."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._config, f, indent=2)
            logger.info("Configuration saved")
        except Exception as e:
            logger.error("Failed to save config: %s", e)

    @property
    def selected_entities(self):
        return self._config.get("selected_entities", [])

    @selected_entities.setter
    def selected_entities(self, entities):
        self._config["selected_entities"] = list(entities)
        self._save()

    @property
    def presets(self):
        return self._config.get("presets", {})

    def save_preset(self, name, entities):
        """Save a named preset of entity selections."""
        if "presets" not in self._config:
            self._config["presets"] = {}
        self._config["presets"][name] = list(entities)
        self._save()

    def load_preset(self, name):
        """Load a named preset. Returns list of entity_ids or None."""
        return self._config.get("presets", {}).get(name)

    def delete_preset(self, name):
        """Delete a named preset."""
        if name in self._config.get("presets", {}):
            del self._config["presets"][name]
            self._save()
            return True
        return False

    @property
    def refresh_interval(self):
        return self._config.get("refresh_interval", 5)

    @refresh_interval.setter
    def refresh_interval(self, value):
        self._config["refresh_interval"] = max(1, min(60, int(value)))
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

    def export_config(self):
        """Export full config as dict for backup."""
        return dict(self._config)

    def import_config(self, data):
        """Import config from dict."""
        self._config.update(data)
        self._save()
