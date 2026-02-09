"""Home Assistant WebSocket API client.

Connects to the HA WebSocket API to fetch entity states in real time.
Uses the Supervisor API token for authentication.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

HA_URL = "http://supervisor/core"


def _get_token():
    """Get the Supervisor token, trying both env var names."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        token = os.environ.get("HASSIO_TOKEN", "")
    return token


class HAClient:
    """Client for communicating with Home Assistant via its REST and WebSocket APIs."""

    def __init__(self):
        self._states = {}
        self._previous_states = {}
        self._areas = {}
        self._entity_registry = {}
        self._device_registry = {}
        self._session = None

    async def start(self):
        """Initialize the HTTP session."""
        token = _get_token()
        logger.info("Supervisor token present: %s (length: %d)", bool(token), len(token))
        self._session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {token}"}
        )
        await self._load_areas()
        await self._load_entity_registry()
        await self._load_device_registry()
        await self.refresh_states()
        logger.info("HA Client started, loaded %d entities", len(self._states))

    async def stop(self):
        """Close the HTTP session."""
        if self._session:
            await self._session.close()

    async def _load_areas(self):
        """Load area registry from HA."""
        try:
            async with self._session.get(f"{HA_URL}/api/config") as resp:
                if resp.status == 200:
                    # Areas are fetched via websocket/template, use a workaround
                    pass
        except Exception as e:
            logger.warning("Failed to load areas: %s", e)

        # Use the template API to get areas
        try:
            async with self._session.post(
                f"{HA_URL}/api/template",
                json={"template": "{{ areas() | list }}"},
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Parse the area IDs
                    area_ids = json.loads(text.replace("'", '"'))
                    for area_id in area_ids:
                        # Get area name
                        async with self._session.post(
                            f"{HA_URL}/api/template",
                            json={"template": f"{{{{ area_name('{area_id}') }}}}"},
                        ) as name_resp:
                            if name_resp.status == 200:
                                name = await name_resp.text()
                                self._areas[area_id] = name.strip()
        except Exception as e:
            logger.warning("Failed to load area names: %s", e)

    async def _load_entity_registry(self):
        """Load entity-to-area mappings via template API."""
        try:
            async with self._session.get(f"{HA_URL}/api/states") as resp:
                if resp.status == 200:
                    states = await resp.json()
                    for state in states:
                        entity_id = state.get("entity_id", "")
                        self._entity_registry[entity_id] = {
                            "entity_id": entity_id,
                        }
        except Exception as e:
            logger.warning("Failed to load entity registry: %s", e)

    async def _load_device_registry(self):
        """Placeholder for device registry loading."""
        pass

    async def _get_entity_area(self, entity_id):
        """Get the area name for an entity using template API."""
        try:
            async with self._session.post(
                f"{HA_URL}/api/template",
                json={"template": f"{{{{ area_name('{entity_id}') }}}}"},
            ) as resp:
                if resp.status == 200:
                    area = (await resp.text()).strip()
                    if area and area != "None" and area != "":
                        return area
        except Exception:
            pass
        return None

    async def refresh_states(self):
        """Fetch all current entity states from HA."""
        try:
            async with self._session.get(f"{HA_URL}/api/states") as resp:
                if resp.status == 200:
                    states = await resp.json()
                    new_states = {}
                    for state in states:
                        entity_id = state.get("entity_id", "")
                        # Track previous state
                        if entity_id in self._states:
                            old = self._states[entity_id]
                            if old.get("state") != state.get("state"):
                                self._previous_states[entity_id] = old.get("state")

                        new_states[entity_id] = state
                    self._states = new_states
                    logger.debug("Refreshed %d entity states", len(self._states))
                else:
                    logger.error("Failed to fetch states: HTTP %d", resp.status)
        except Exception as e:
            logger.error("Error refreshing states: %s", e)

    def get_all_entities(self):
        """Return all entities grouped by domain."""
        domains = {}
        for entity_id, state in self._states.items():
            domain = entity_id.split(".")[0]
            if domain not in domains:
                domains[domain] = []
            attrs = state.get("attributes", {})
            domains[domain].append({
                "entity_id": entity_id,
                "friendly_name": attrs.get("friendly_name", entity_id),
                "state": state.get("state", "unknown"),
                "domain": domain,
                "device_class": attrs.get("device_class"),
                "unit_of_measurement": attrs.get("unit_of_measurement"),
                "icon": attrs.get("icon"),
            })
        # Sort entities within each domain
        for domain in domains:
            domains[domain].sort(key=lambda e: e.get("friendly_name", "").lower())
        return domains

    async def get_exposed_data(self, selected_entities, filter_unavailable=True, compact=False):
        """Get data for selected entities in the AI endpoint format."""
        sensors = []
        now = datetime.now(timezone.utc).isoformat()

        for entity_id in selected_entities:
            if entity_id not in self._states:
                continue

            state = self._states[entity_id]
            current_state = state.get("state", "unknown")

            # Filter unavailable/unknown if requested
            if filter_unavailable and current_state in ("unavailable", "unknown"):
                continue

            if compact:
                sensors.append({
                    "entity_id": entity_id,
                    "state": current_state,
                })
            else:
                attrs = state.get("attributes", {})
                last_state = self._previous_states.get(entity_id, current_state)
                area = await self._get_entity_area(entity_id)

                entry = {
                    "entity_id": entity_id,
                    "friendly_name": attrs.get("friendly_name", entity_id),
                    "state": current_state,
                    "last_state": last_state,
                    "last_changed": state.get("last_changed", now),
                    "unit_of_measurement": attrs.get("unit_of_measurement"),
                    "device_class": attrs.get("device_class"),
                    "area": area,
                }

                # Add useful extra attributes if present
                extra_attrs = {}
                for key in ("battery_level", "temperature", "humidity", "brightness", "color_temp"):
                    if key in attrs:
                        extra_attrs[key] = attrs[key]
                if extra_attrs:
                    entry["attributes"] = extra_attrs

                sensors.append(entry)

        return {
            "sensors": sensors,
            "last_updated": now,
            "total_sensors": len(sensors),
        }

    async def periodic_refresh(self, interval=5):
        """Background task to periodically refresh states."""
        while True:
            await asyncio.sleep(interval)
            await self.refresh_states()
