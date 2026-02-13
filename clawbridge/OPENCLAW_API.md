# ClawBridge API Reference

This document is the API reference for AI agents (e.g., OpenClaw) integrating with ClawBridge. ClawBridge exposes a filtered subset of Home Assistant entities and services for safe AI-controlled automation.

**Base URL:** `http://localhost:8100` (or your ClawBridge host)

---

## Authentication

If API keys are configured, include the bearer token in requests:

```
Authorization: Bearer cb_xxxx
```

If no API keys are configured, access is open and no `Authorization` header is required.

---

## Access Levels

Entities are assigned one of four access levels:

| Level    | Description |
|----------|-------------|
| `off`    | Entity is hidden from AI entirely. Not returned in any endpoint. |
| `read`   | AI can read state but cannot control. Service calls return 403. |
| `confirm`| AI can request actions, but they require human approval via phone notification (Approve/Deny buttons). Returns `202 Accepted` with an `action_id` for polling. |
| `control`| AI can call services directly; requests are proxied to Home Assistant. |

**Note:** Some domains are inherently read-only (e.g., `sensor`, `binary_sensor`, `weather`, `sun`, `person`, `device_tracker`) and only support `off` or `read`. These entities will never have `confirm` or `control` access.

---

## Rate Limiting

- **Service calls:** 60 requests/minute per IP (default)
- **History API:** 10 requests/minute per IP

---

## Endpoints

### 1. Health Check

**GET** `/api/`

Returns API status.

**Response:**
```json
{"message": "API running."}
```

---

### 2. Configuration

**GET** `/api/config`

Returns exposed domain list and version information.

---

### 3. All Entity States

**GET** `/api/states`

Returns all exposed entity states in Home Assistant format.

**Response (each state object):**
- `entity_id` (string)
- `state` (string)
- `attributes` (object)
- `last_changed` (ISO 8601)
- `last_updated` (ISO 8601)
- `context` (object)
- `annotation` (optional, string): User-provided description
- `constraints` (optional, object): Parameter limits
- `access_level` (optional, string): `"read"` | `"confirm"` | `"control"`

---

### 4. Single Entity State

**GET** `/api/states/{entity_id}`

Returns state for one entity. Same enriched format as above.

**Response:** 404 if entity is not exposed.

---

### 5. Available Services

**GET** `/api/services`

Returns available services for domains that have control or confirm entities.

---

### 6. Call Service

**POST** `/api/services/{domain}/{service}`

Calls a Home Assistant service.

**Request body:**
```json
{
  "entity_id": "light.office",
  "brightness": 200
}
```

**Behavior by access level:**
- **read:** Returns 403 Forbidden
- **confirm:** Returns `202 Accepted` with `action_id` for polling. A push notification with Approve/Deny buttons is sent to the user's phone.
- **control:** Proxied directly to Home Assistant

**Validation:**
- Parameters are validated against constraints (clamped to min/max). Only parameters the entity actually supports are constrained.
- Schedule restrictions apply: 403 if outside allowed time window
- Subject to rate limiting

---

### 7. Parameter Constraints

**GET** `/api/constraints`

Returns all parameter constraints for exposed entities.

---

### 8. History

**GET** `/api/history/period/{timestamp}`

Proxies to Home Assistant history API, filtered to exposed entities only.

**Query parameters:**
- `filter_entity_id` (optional): Comma-separated entity IDs
- `end_time` (optional): End of period

**Rate limit:** 10 requests/minute.

---

### 9. Confirmation Action Status

**GET** `/api/actions/{action_id}`

Poll status of a confirmation action (for `confirm`-level entities).

**Response:**
- `action_id` (string)
- `status` (string): `"pending"` | `"approved"` | `"denied"` | `"expired"`
- `entity_id` (string)
- `domain` (string)
- `service` (string)

---

### 10. WebSocket

**GET** `/api/websocket`

WebSocket endpoint for real-time state changes.

**Protocol:**

1. Server sends: `{"type": "auth_required"}`
2. Client sends: `{"type": "auth", "api_key": "cb_xxxx"}` (omit `api_key` if no keys configured)
3. Server sends: `{"type": "auth_ok"}`
4. Server pushes: `{"type": "state_changed", "entity_id": "...", "new_state": {...}, "old_state": {...}}`
5. Client may send: `{"type": "subscribe", "entity_ids": ["light.office"]}` to narrow subscription

---

### 11. Legacy Endpoints

**GET** `/api/ai-sensors`

Returns ClawBridge-format sensor data (legacy).

**POST** `/api/ai-action`

ClawBridge-format service call (legacy).

---

## Python Usage Examples

### Fetching States

```python
import requests

BASE_URL = "http://localhost:8100"
HEADERS = {"Authorization": "Bearer cb_xxxx"}  # Omit if no keys configured

# Get all states
resp = requests.get(f"{BASE_URL}/api/states", headers=HEADERS)
states = resp.json()

# Get single entity
resp = requests.get(f"{BASE_URL}/api/states/light.office", headers=HEADERS)
if resp.status_code == 200:
    state = resp.json()
    print(f"{state['entity_id']}: {state['state']}")
elif resp.status_code == 404:
    print("Entity not exposed")
```

### Calling a Service

```python
import requests

BASE_URL = "http://localhost:8100"
HEADERS = {"Authorization": "Bearer cb_xxxx", "Content-Type": "application/json"}

# Direct control (control-level entity)
resp = requests.post(
    f"{BASE_URL}/api/services/light/turn_on",
    headers=HEADERS,
    json={"entity_id": "light.office", "brightness": 200}
)

if resp.status_code == 200:
    print("Service called successfully")
elif resp.status_code == 403:
    print("Access denied: read-only or schedule restriction")
```

### Handling Confirmations

```python
import requests
import time

BASE_URL = "http://localhost:8100"
HEADERS = {"Authorization": "Bearer cb_xxxx", "Content-Type": "application/json"}

# Request action on confirm-level entity
resp = requests.post(
    f"{BASE_URL}/api/services/switch/turn_on",
    headers=HEADERS,
    json={"entity_id": "switch.heater"}
)

if resp.status_code == 202:
    data = resp.json()
    action_id = data["action_id"]

    # Poll for result
    while True:
        poll = requests.get(f"{BASE_URL}/api/actions/{action_id}", headers=HEADERS)
        result = poll.json()

        if result["status"] == "approved":
            print("Action approved and executed")
            break
        elif result["status"] == "denied":
            print("Action denied by user")
            break
        elif result["status"] == "expired":
            print("Action expired")
            break

        time.sleep(1)
```

### Using WebSocket

```python
import asyncio
import websockets
import json

async def watch_states():
    uri = "ws://localhost:8100/api/websocket"

    async with websockets.connect(uri) as ws:
        # Auth flow
        msg = await ws.recv()
        data = json.loads(msg)
        if data.get("type") == "auth_required":
            await ws.send(json.dumps({"type": "auth", "api_key": "cb_xxxx"}))
            # Omit api_key if no keys: {"type": "auth"}

        auth_ok = await ws.recv()
        assert json.loads(auth_ok).get("type") == "auth_ok"

        # Subscribe to specific entities
        await ws.send(json.dumps({
            "type": "subscribe",
            "entity_ids": ["light.office", "sensor.temperature"]
        }))

        # Listen for state changes
        async for raw in ws:
            evt = json.loads(raw)
            if evt.get("type") == "state_changed":
                print(f"{evt['entity_id']}: {evt['old_state']['state']} -> {evt['new_state']['state']}")

asyncio.run(watch_states())
```

### Managing To-Do Lists

**Reading to-do list items** — Works even with `read` access. ClawBridge automatically sets `return_response: true` so the full item list is returned:

```python
import requests

BASE_URL = "http://localhost:8100"
HEADERS = {"Authorization": "Bearer cb_xxxx", "Content-Type": "application/json"}

# Get all items from a to-do list (works with read, confirm, or control access)
resp = requests.post(
    f"{BASE_URL}/api/services/todo/get_items",
    headers=HEADERS,
    json={"entity_id": "todo.shopping_list"}
)
# Response contains:
# {
#   "todo.shopping_list": {
#     "items": [
#       {"summary": "Milk", "status": "needs_action", "uid": "..."},
#       {"summary": "Bread", "status": "completed", "uid": "..."}
#     ]
#   }
# }
```

**Modifying to-do list items** — Requires `confirm` or `control` access:

```python
# Add item to a to-do list
resp = requests.post(
    f"{BASE_URL}/api/services/todo/add_item",
    headers=HEADERS,
    json={"entity_id": "todo.shopping_list", "item": "Milk"}
)

# Mark item as completed
resp = requests.post(
    f"{BASE_URL}/api/services/todo/update_item",
    headers=HEADERS,
    json={"entity_id": "todo.shopping_list", "item": "Milk", "status": "completed"}
)
```

### Creating Calendar Events

```python
import requests

BASE_URL = "http://localhost:8100"
HEADERS = {"Authorization": "Bearer cb_xxxx", "Content-Type": "application/json"}

resp = requests.post(
    f"{BASE_URL}/api/services/calendar/create_event",
    headers=HEADERS,
    json={
        "entity_id": "calendar.family",
        "summary": "Dentist appointment",
        "start_date_time": "2026-02-15T10:00:00",
        "end_date_time": "2026-02-15T11:00:00"
    }
)
```

### Querying History

```python
import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8100"
HEADERS = {"Authorization": "Bearer cb_xxxx"}

# History for last 24 hours
end = datetime.utcnow()
start = end - timedelta(hours=24)
timestamp = start.strftime("%Y-%m-%dT%H:%M:%S")

url = f"{BASE_URL}/api/history/period/{timestamp}"
params = {"end_time": end.strftime("%Y-%m-%dT%H:%M:%S")}
# Optional: filter_entity_id=light.office,sensor.temperature

resp = requests.get(url, headers=HEADERS, params=params)

if resp.status_code == 200:
    # Each element is a list of state changes for one entity
    history = resp.json()
    for entity_history in history:
        for change in entity_history:
            print(f"{change['entity_id']}: {change['state']} at {change['last_changed']}")
```

---

## Summary Table

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/` | Health check |
| GET | `/api/config` | Config, domains, version |
| GET | `/api/states` | All entity states |
| GET | `/api/states/{entity_id}` | Single entity state |
| GET | `/api/services` | Available services |
| POST | `/api/services/{domain}/{service}` | Call service |
| GET | `/api/constraints` | Parameter constraints |
| GET | `/api/history/period/{timestamp}` | History (filtered) |
| GET | `/api/actions/{action_id}` | Poll confirmation status |
| GET | `/api/websocket` | WebSocket real-time updates |
| GET | `/api/ai-sensors` | Legacy sensor format |
| POST | `/api/ai-action` | Legacy action format |
