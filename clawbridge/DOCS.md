# ClawBridge Documentation (v1.4.0)

ClawBridge provides an **AI guard rail** between AI agents (OpenClaw, etc.) and Home Assistant. Users maintain explicit control over which entities are exposed for reading and/or control, with granular access levels, human-in-the-loop confirmation, and multi-agent security.

---

## Architecture Overview

| Component | Port | Authentication | Purpose |
|-----------|------|----------------|---------|
| **Setup UI** | 8099 | Home Assistant Ingress | Configure entities, presets, security, audit logs |
| **AI Data Plane** | 8100 | Optional Bearer API keys | REST + WebSocket API for AI clients |

- **Setup UI**: Browse entities, set access levels, manage presets, configure API keys, schedules, and security. Fully protected by HA ingress.
- **AI Data Plane**: HA-compatible REST and WebSocket endpoints that expose only configured entities and proxy only allowed service calls.

---

## Access Levels

Each entity has one of **four** access levels:

| Level | AI Can See State | AI Can Call Services | Behavior |
|-------|------------------|----------------------|----------|
| **Off** | No | No | Entity hidden from AI. No state, no services. |
| **Read** | Yes | No | AI can read state only. No service calls. |
| **Confirm** | Yes | Yes (queued) | AI can call services, but request returns **202 Accepted**. Action is queued until a human approves it via the HA notification. |
| **Control** | Yes | Yes (immediate) | AI can call services directly. Action executes immediately. |

### Read-Only Domains

Some entity domains are inherently read-only and only support **Off** or **Read** access. The UI hides the Confirm and Control options for these domains:

`sensor`, `binary_sensor`, `weather`, `sun`, `zone`, `person`, `device_tracker`, `geo_location`, `air_quality`, `image`

All other domains (including `light`, `switch`, `climate`, `todo`, `calendar`, `cover`, `lock`, etc.) support all four access levels.

### Examples

- **Off**: `lock.front_door` — AI cannot see or control the lock.
- **Read**: `sensor.front_door` — AI knows when the door opens, but cannot unlock.
- **Confirm**: `cover.garage` — AI can request to open, but you must approve via phone notification (Approve/Deny buttons).
- **Control**: `light.office` — AI can turn on/off immediately.
- **Read (sensor)**: `sensor.temperature` — AI can see the value. Confirm/Control not available (read-only domain).

---

## AI Endpoints (Port 8100)

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/` | API health check |
| `GET` | `/api/config` | Minimal config (exposed domains, annotations) |
| `GET` | `/api/states` | All exposed entity states (read, confirm, control) |
| `GET` | `/api/states/{entity_id}` | Single entity state (404 if not exposed) |
| `GET` | `/api/services` | Services for domains with control or confirm entities |
| `POST` | `/api/services/{domain}/{service}` | Call a service (control = immediate; confirm = 202 queued) |
| `GET` | `/api/context` | Full AI context: permissions, entities, annotations, constraints, schedules, services |
| `GET` | `/api/history/period` | State history (proxy HA history API, filtered to exposed entities) |

### Legacy Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/ai-sensors` | ClawBridge-format sensor data + access info |
| `POST` | `/api/ai-action` | ClawBridge-format service call |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `WS /api/websocket` | Real-time state streaming. State changes for exposed entities are pushed to connected AI clients. |

---

## AI Context Endpoint

`GET /api/context` returns everything the AI needs in a single call: a summary of its permissions, entities grouped by access level, user-written annotations, parameter constraints, active time schedules, available services, and human-readable limitations. This is the **recommended first call** for any AI agent to understand its current capabilities before taking action.

---

## Entity Annotations

Each entity can have a **user-written description** (annotation) that is visible to the AI. Annotations help the AI understand context (e.g., "Main living room light, dims at sunset").

- Annotations are returned in `GET /api/config` and alongside state in extended responses.
- Use annotations to clarify ambiguous entity names or add usage notes.

---

## Parameter Constraints

For service call parameters (e.g., `brightness`, `temperature`), you can define:

- **Min / max** numeric limits
- **Auto-clamping**: values outside the range are automatically clamped to the nearest valid value before the service call is executed

The constraint editor is **smart** — it only shows parameters the entity actually supports (based on its real Home Assistant attributes). For example, a simple on/off light won't show brightness or color_temp options, while a dimmable light will.

Example: `brightness` for `light.office` constrained to 1–255. If AI sends `brightness: 500`, it is clamped to 255.

---

## Service Call Validation Flow

When AI calls `POST /api/services/{domain}/{service}`:

1. **Access level check**: Entity must be **control** (immediate) or **confirm** (queued, 202).
2. **Time schedule check**: If entity has a time-based schedule, control is only allowed during allowed hours.
3. **Entity domain match**: Entity domain must match the URL domain.
4. **Parameter constraints**: Parameters are validated and auto-clamped to configured min/max.
5. **API key scope** (if Bearer auth): Entity must be in the key’s allowed scope.
6. **Rate limiting**: Per-IP and per-key limits apply.
7. **IP allowlist**: Request IP must be allowed (if configured).
8. **Audit logging**: Request is logged (success, denied, or queued).
9. **Confirm entities**: Returns **202 Accepted**; HA notification is sent for human approval.
10. **Control entities**: Executes immediately; returns standard HA response.

If denied, returns **403** with an explanation.

---

## Example Service Call

```http
POST http://<ha-ip>:8100/api/services/light/turn_on
Content-Type: application/json
Authorization: Bearer <optional-api-key>

{
  "entity_id": "light.office",
  "brightness": 200,
  "rgb_color": [255, 128, 0]
}
```

**Response (control entity, success):**
```json
[
  {
    "context": { "id": "..." },
    "entity_id": "light.office",
    "state": "on",
    ...
  }
]
```

**Response (confirm entity, queued):**
```
HTTP/1.1 202 Accepted
```
Action is queued; HA notification sent for human approval.

---

## Multi-Agent API Keys

- **Optional Bearer authentication** for the AI data plane.
- Each key can have **per-key entity scoping**: limit which entities that key can access.
- Keys are managed in the Setup UI (Security tab).
- Rate limiting can apply **per-key** in addition to per-IP.

---

## Time-Based Access Schedules

- **Named schedules** define allowed hours (e.g., "Business Hours" 9–17).
- Assign schedules to entities to **restrict control** to certain times.
- Outside the schedule, control and confirm actions are denied; read remains available.

---

## Human-in-the-Loop Confirmation

For entities with **confirm** access:

1. AI sends service call → ClawBridge returns **202 Accepted** with an `action_id`.
2. Action is queued; an **actionable push notification** is sent to your phone (iOS and Android via HA Companion App) with **Approve** and **Deny** buttons.
3. Tap **Approve** to execute the action, or **Deny** to reject it. You can also poll `GET /api/actions/{action_id}` for the status.
4. Actions expire after a configurable timeout (default 5 minutes).

The notification message uses the **AI name** (configurable in Settings, e.g., "OpenClaw") and the **device friendly name** (e.g., "Office Light") instead of raw entity IDs.

---

## Usage Dashboard

- **Stats cards**: Total requests, success rate, top entities.
- **Hourly chart**: Request volume over time.
- **Top entities**: Most frequently called entities.

---

## Security Features

| Feature | Description |
|---------|-------------|
| **AI guard rail** | AI sees/calls only what you expose |
| **Four access levels** | Off / Read / Confirm / Control |
| **Human-in-the-loop** | Confirm entities require phone approval (actionable Approve/Deny buttons) |
| **Multi-agent API keys** | Optional Bearer auth, per-key entity scoping |
| **Rate limiting** | Per-IP and per-key |
| **IP allowlist** | Restrict which IPs can access port 8100 |
| **Audit logging** | All service calls (success, denied, queued) with retention |
| **Sensitive domain warnings** | lock, cover, alarm, climate, valve require explicit confirmation |
| **Parameter constraints** | Min/max limits, auto-clamping, smart filtering by entity capabilities |
| **Time-based schedules** | Restrict control to allowed hours |
| **Read-only domain filtering** | sensor, binary_sensor, weather, etc. limited to off/read only |

---

## Light / Dark Theme

ClawBridge includes both a dark (default) and light theme. Toggle between them using the **sun/moon button** in the sidebar header. Your preference is saved in the browser's `localStorage` and persists across sessions.

---

## AI Chat

The Chat tab lets you talk directly to your AI from inside ClawBridge. It works by proxying messages to your OpenClaw Gateway (or any OpenAI-compatible `/v1/chat/completions` endpoint).

### Setup

1. Go to **Settings → Chat / AI Gateway**
2. Enter your Gateway URL (e.g., `http://192.168.1.50:8080`)
3. Enter a Bearer token if required
4. Click **Test** to verify connectivity
5. Open the **Chat** tab and start a conversation

### How It Works

- Messages are sent via `POST /api/chat` on the ingress port (8099, authenticated)
- ClawBridge streams the Gateway response as SSE events back to the browser
- Chat history is saved server-side (capped at 200 messages) and persists across sessions
- Use the **New** button to clear history and start a fresh conversation

### Chat Endpoints (Ingress Port Only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Send message, stream SSE response from gateway |
| `GET` | `/api/chat/history` | Get saved chat history |
| `POST` | `/api/chat/history` | Save chat history |
| `DELETE` | `/api/chat/history` | Clear chat history |
| `GET` | `/api/chat/status` | Check if gateway is configured |

---

## Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Refresh Interval | Seconds between state refreshes | 5 |
| Filter Unavailable | Exclude unavailable/unknown entities | On |
| Compact Mode | Minimal JSON in legacy endpoint | Off |
| Audit Logging | Log all AI service calls | On |
| Audit Retention | Days to keep audit logs | 30 |
| Rate Limit (per IP) | Max service calls/minute per IP | 60 |
| Rate Limit (per key) | Max service calls/minute per API key | 60 |
| IP Allowlist | Restrict port 8100 access (empty = all) | Empty |
| AI Name | Name shown in confirmation notifications (e.g., "OpenClaw") | AI |
| Confirm Timeout | Seconds before pending confirm actions expire | 300 |
| Sensitive Domains | Domains requiring explicit control confirmation | lock, cover, alarm_control_panel, climate, valve |
| Gateway URL | OpenClaw Gateway URL for chat proxy | Empty |
| Gateway Token | Bearer token for gateway auth | Empty |

---

## Presets

- **Named presets** save the current entity access configuration.
- **Import/Export**: Export config to JSON; import from file to restore or share setups.

---

## Setup

1. Install the add-on from the repository
2. Start the add-on
3. Open the Web UI from the sidebar
4. **Entities tab**: Browse domains, set each entity to **off**, **read**, **confirm**, or **control**
5. Add entity annotations and parameter constraints as needed
6. **Security tab**: Configure API keys, schedules, and view pending approvals
7. **Settings tab**: Configure refresh, rate limits, IP allowlist, audit logging
8. **Settings → Chat / AI Gateway**: Enter Gateway URL and token to enable the Chat tab
9. **Chat tab**: Talk to your AI directly from ClawBridge
10. Share the AI endpoint URL: `http://<your-ha-ip>:8100/api/`
11. For WebSocket: `ws://<your-ha-ip>:8100/api/websocket`
