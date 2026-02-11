# ClawBridge API Reference for OpenClaw

This document describes the API that OpenClaw (or any AI agent) should use to interact with Home Assistant through ClawBridge. ClawBridge acts as an air gap -- you can only see and control entities that the user has explicitly exposed.

## Base URL

```
http://<home-assistant-ip>:8100
```

No authentication required. You may send an `Authorization: Bearer <any_value>` header if your client library requires one -- it will be accepted and ignored.

---

## Endpoints

### 1. Health Check

```
GET /api/
```

**Response:**
```json
{"message": "API running."}
```

---

### 2. Get All Entity States

```
GET /api/states
```

Returns the current state of every entity the user has exposed (both read-only and controllable). The response format matches Home Assistant's `/api/states` exactly.

**Response:**
```json
[
  {
    "entity_id": "light.office",
    "state": "on",
    "attributes": {
      "friendly_name": "Office Light",
      "brightness": 180,
      "color_mode": "brightness",
      "supported_features": 0
    },
    "last_changed": "2026-02-10T14:30:00+00:00",
    "last_updated": "2026-02-10T14:30:05+00:00",
    "context": {"id": "...", "parent_id": null, "user_id": null}
  },
  {
    "entity_id": "sensor.front_door",
    "state": "off",
    "attributes": {
      "friendly_name": "Front Door Sensor",
      "device_class": "door"
    },
    "last_changed": "2026-02-10T12:00:00+00:00",
    "last_updated": "2026-02-10T14:30:05+00:00",
    "context": {"id": "...", "parent_id": null, "user_id": null}
  }
]
```

**Note:** Entities the user has not exposed will NOT appear here. Do not assume any entity exists unless it appears in this response.

---

### 3. Get Single Entity State

```
GET /api/states/{entity_id}
```

Returns state for one entity. Returns 404 if the entity is not exposed (regardless of whether it exists in Home Assistant).

**Example:**
```
GET /api/states/light.office
```

**Response (200):**
```json
{
  "entity_id": "light.office",
  "state": "on",
  "attributes": {
    "friendly_name": "Office Light",
    "brightness": 180
  },
  "last_changed": "2026-02-10T14:30:00+00:00",
  "last_updated": "2026-02-10T14:30:05+00:00",
  "context": {"id": "...", "parent_id": null, "user_id": null}
}
```

**Response (404 -- entity not exposed):**
```json
{"message": "Entity not found: light.bedroom"}
```

---

### 4. Get Available Services

```
GET /api/services
```

Returns the list of services available for domains where the user has exposed at least one entity with **control** access. This tells you what actions you can take.

**Response:**
```json
[
  {
    "domain": "light",
    "services": ["turn_on", "turn_off", "toggle"]
  },
  {
    "domain": "switch",
    "services": ["turn_on", "turn_off", "toggle"]
  }
]
```

**Note:** If a domain is not listed here, you cannot call services on entities in that domain (even if you can see their state). The user has granted those entities read-only access.

---

### 5. Call a Service

```
POST /api/services/{domain}/{service}
```

Calls a Home Assistant service on one or more entities. This is how you control devices.

**Request body:**
```json
{
  "entity_id": "light.office",
  "brightness": 200
}
```

**Rules:**
- The `entity_id` must be exposed with **control** access by the user
- The entity domain must match the URL domain (e.g. `light.office` must be called via `/api/services/light/...`)
- If the entity is exposed as **read-only**, you will get a 403
- If the entity is not exposed at all, you will get a 403

**Response (200 -- success):**
The response is a JSON array of states that changed (same format as Home Assistant).

**Response (403 -- read-only entity):**
```json
{"message": "Entity light.bedroom is read-only. Control access not granted."}
```

**Response (403 -- entity not exposed):**
```json
{"message": "Entity not exposed: light.secret_room"}
```

**Response (429 -- rate limited):**
```json
{"message": "Rate limit exceeded. Try again later."}
```

---

### 6. Get Sensor Data (Legacy)

```
GET /api/ai-sensors
```

ClawBridge-specific format with extra metadata. Returns all exposed entities plus access level information.

**Response:**
```json
{
  "sensors": [
    {
      "entity_id": "light.office",
      "friendly_name": "Office Light",
      "state": "on",
      "last_state": "off",
      "last_changed": "2026-02-10T14:30:00+00:00",
      "unit_of_measurement": null,
      "device_class": null,
      "area": "Office"
    }
  ],
  "last_updated": "2026-02-10T14:35:00+00:00",
  "total_sensors": 1,
  "entity_access": {
    "light.office": "control",
    "sensor.front_door": "read"
  },
  "controllable_entities": ["light.office"],
  "control_domains": ["light"]
}
```

---

### 7. Call a Service (Legacy)

```
POST /api/ai-action
```

Alternative to the HA-compatible service endpoint.

**Request body:**
```json
{
  "service": "light.turn_on",
  "entity_id": "light.office",
  "data": {"brightness": 200}
}
```

**Response (200):**
```json
{"status": "ok", "result": [...]}
```

---

## Access Levels Explained

The user configures each entity with one of these access levels:

| Access | You can read state | You can call services |
|--------|-------------------|----------------------|
| **read** | Yes | No (403 if attempted) |
| **control** | Yes | Yes |

Entities not exposed at all will return 404 on `/api/states/{entity_id}` and will not appear in `/api/states`.

**How to check what you can control:**
1. Call `GET /api/services` -- the listed domains are your controllable domains
2. Call `GET /api/states` -- cross-reference with the domains above
3. Or use `GET /api/ai-sensors` which includes `entity_access` and `controllable_entities`

---

## Rate Limiting

Service calls (`POST /api/services/...`) are rate-limited per IP address. Default: 60 requests/minute. If exceeded, you receive a 429 response. Wait and retry.

State queries (`GET /api/states`, `GET /api/states/{id}`) are NOT rate-limited.

---

## Error Handling

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Bad request (malformed JSON, domain mismatch) |
| 403 | Entity not exposed, or read-only, or IP blocked |
| 404 | Entity not found (not exposed) |
| 429 | Rate limit exceeded |
| 502 | Home Assistant returned an error |

All error responses include a `message` field:
```json
{"message": "Descriptive error message here"}
```

---

## Usage with Standard HA Client Libraries

ClawBridge's port 8100 API is designed to be compatible with Home Assistant REST API client libraries. Example with Python:

```python
import requests

BASE = "http://192.168.1.100:8100"
HEADERS = {"Authorization": "Bearer dummy", "Content-Type": "application/json"}

# Get all available entities
states = requests.get(f"{BASE}/api/states", headers=HEADERS).json()
for entity in states:
    print(f"{entity['entity_id']}: {entity['state']}")

# Check what services are available
services = requests.get(f"{BASE}/api/services", headers=HEADERS).json()
for svc in services:
    print(f"{svc['domain']}: {svc['services']}")

# Turn on a light
requests.post(
    f"{BASE}/api/services/light/turn_on",
    headers=HEADERS,
    json={"entity_id": "light.office", "brightness": 200}
)
```

---

## Audit Trail

All service calls (successful and denied) are logged by ClawBridge. The user can review these logs in the ClawBridge web UI under the **Audit** tab. Each log entry records:

- Timestamp
- Entity ID
- Domain and service called
- Result (success, denied, error, rate_limited)
- Source IP address
- Response time

If you receive a 403 and believe you should have access, ask the user to check ClawBridge's entity settings and grant the appropriate access level.
