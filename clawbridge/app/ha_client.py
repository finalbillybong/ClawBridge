"""Home Assistant API client.

Connects to HA via REST API for state polling and service calls.
Supports WebSocket for real-time state change subscriptions.
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
HA_WS_URL = "ws://supervisor/core/websocket"


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
        # WebSocket
        self._ws = None
        self._ws_task = None
        self._ws_msg_id = 1
        self._state_change_callbacks = []
        self._ws_connected = False

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
        # Start WebSocket connection for real-time updates
        self._ws_task = asyncio.create_task(self._ws_listener())

    async def stop(self):
        """Close the HTTP session and WebSocket."""
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    # ── WebSocket for real-time state changes ─────

    async def _ws_listener(self):
        """Maintain a persistent WebSocket connection to HA for state_changed events."""
        token = _get_token()
        while True:
            try:
                async with self._session.ws_connect(HA_WS_URL) as ws:
                    self._ws = ws
                    logger.info("WebSocket connected to HA")

                    # HA sends auth_required first
                    msg = await ws.receive_json()
                    if msg.get("type") == "auth_required":
                        await ws.send_json({"type": "auth", "access_token": token})
                        auth_result = await ws.receive_json()
                        if auth_result.get("type") != "auth_ok":
                            logger.error("WebSocket auth failed: %s", auth_result)
                            await asyncio.sleep(10)
                            continue

                    self._ws_connected = True
                    logger.info("WebSocket authenticated with HA")

                    # Subscribe to state_changed events
                    sub_id = self._ws_msg_id
                    self._ws_msg_id += 1
                    await ws.send_json({
                        "id": sub_id,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    })

                    async for raw_msg in ws:
                        if raw_msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(raw_msg.data)
                            except json.JSONDecodeError:
                                continue

                            if data.get("type") == "event":
                                event = data.get("event", {})
                                event_data = event.get("data", {})
                                entity_id = event_data.get("entity_id")
                                new_state = event_data.get("new_state")
                                old_state = event_data.get("old_state")

                                if entity_id and new_state:
                                    # Update internal state cache
                                    if entity_id in self._states:
                                        old_cached = self._states[entity_id]
                                        if old_cached.get("state") != new_state.get("state"):
                                            self._previous_states[entity_id] = old_cached.get("state")
                                    self._states[entity_id] = new_state

                                    # Notify callbacks
                                    for callback in self._state_change_callbacks:
                                        try:
                                            await callback(entity_id, new_state, old_state)
                                        except Exception as e:
                                            logger.error("State change callback error: %s", e)

                        elif raw_msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("WebSocket connection lost: %s. Reconnecting in 5s...", e)
            finally:
                self._ws_connected = False
                self._ws = None

            await asyncio.sleep(5)

    def subscribe_state_changes(self, callback):
        """Register a callback for state changes: async callback(entity_id, new_state, old_state)."""
        self._state_change_callbacks.append(callback)

    def unsubscribe_state_changes(self, callback):
        """Unregister a state change callback."""
        self._state_change_callbacks = [cb for cb in self._state_change_callbacks if cb is not callback]

    @property
    def ws_connected(self):
        """Whether the HA WebSocket is connected."""
        return self._ws_connected

    # ── Area / Registry loading ───────────────────

    async def _load_areas(self):
        """Load area registry from HA."""
        try:
            async with self._session.get(f"{HA_URL}/api/config") as resp:
                if resp.status == 200:
                    pass
        except Exception as e:
            logger.warning("Failed to load areas: %s", e)

        try:
            async with self._session.post(
                f"{HA_URL}/api/template",
                json={"template": "{{ areas() | list }}"},
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    area_ids = json.loads(text.replace("'", '"'))
                    for area_id in area_ids:
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

    # ── State management ──────────────────────────

    async def refresh_states(self):
        """Fetch all current entity states from HA."""
        try:
            async with self._session.get(f"{HA_URL}/api/states") as resp:
                if resp.status == 200:
                    states = await resp.json()
                    new_states = {}
                    for state in states:
                        entity_id = state.get("entity_id", "")
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

    def get_ha_format_states(self, entity_ids, filter_unavailable=True):
        """Return states in Home Assistant's exact /api/states JSON format for given entity_ids."""
        results = []
        for entity_id in entity_ids:
            if entity_id not in self._states:
                continue
            state = self._states[entity_id]
            current = state.get("state", "unknown")
            if filter_unavailable and current in ("unavailable", "unknown"):
                continue
            results.append({
                "entity_id": entity_id,
                "state": current,
                "attributes": state.get("attributes", {}),
                "last_changed": state.get("last_changed", ""),
                "last_updated": state.get("last_updated", ""),
                "context": state.get("context", {"id": "", "parent_id": None, "user_id": None}),
            })
        return results

    def get_ha_format_single(self, entity_id):
        """Return a single entity state in HA format, or None if not found."""
        if entity_id not in self._states:
            return None
        state = self._states[entity_id]
        return {
            "entity_id": entity_id,
            "state": state.get("state", "unknown"),
            "attributes": state.get("attributes", {}),
            "last_changed": state.get("last_changed", ""),
            "last_updated": state.get("last_updated", ""),
            "context": state.get("context", {"id": "", "parent_id": None, "user_id": None}),
        }

    # ── History ───────────────────────────────────

    async def get_history(self, start_time, entity_ids, end_time=None):
        """Fetch state history from HA for specific entities.
        Returns list of lists (one per entity) of state objects.
        """
        try:
            params = {
                "filter_entity_id": ",".join(entity_ids),
                "minimal_response": "true",
            }
            if end_time:
                params["end_time"] = end_time

            url = f"{HA_URL}/api/history/period/{start_time}"
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("Failed to fetch history: HTTP %d", resp.status)
        except Exception as e:
            logger.warning("Failed to fetch history: %s", e)
        return []

    # ── Services ──────────────────────────────────

    async def get_services(self):
        """Fetch available HA services (domain -> list of service names). Returns dict."""
        try:
            async with self._session.get(f"{HA_URL}/api/services") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {item["domain"]: item.get("services", []) for item in data}
                logger.warning("Failed to fetch services: HTTP %d", resp.status)
        except Exception as e:
            logger.warning("Failed to fetch services: %s", e)
        return {}

    async def call_service(self, domain, service, service_data):
        """Call a Home Assistant service. service_data is the JSON body (e.g. entity_id, etc.)."""
        try:
            url = f"{HA_URL}/api/services/{domain}/{service}"
            async with self._session.post(url, json=service_data) as resp:
                if resp.status in (200, 201):
                    return True, await resp.json()
                body = await resp.text()
                logger.warning("Service call failed: %s/%s HTTP %d %s", domain, service, resp.status, body[:200])
                return False, {"error": body or f"HTTP {resp.status}"}
        except Exception as e:
            logger.exception("Error calling service %s.%s: %s", domain, service, e)
            return False, {"error": str(e)}

    async def periodic_refresh(self, interval=5):
        """Background task to periodically refresh states."""
        while True:
            await asyncio.sleep(interval)
            await self.refresh_states()
