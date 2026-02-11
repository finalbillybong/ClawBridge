# ClawBridge

Bidirectional air gap between AI agents (OpenClaw) and Home Assistant. Users maintain explicit control over which entities are exposed for reading and/or control.

## How It Works

1. **Setup UI** (Port 8099, authenticated via HA ingress) -- Browse entities, set access levels (read-only or control), manage presets, view audit logs, configure security settings.

2. **AI Data Plane** (Port 8100, unauthenticated) -- HA-compatible REST API endpoints that return only exposed entities and proxy only allowed service calls.

## Setup

1. Install the add-on from the repository
2. Start the add-on
3. Open the Web UI from the sidebar
4. **Entities tab**: browse domains, set each entity to **read** (AI can see state) or **control** (AI can see + call services)
5. **Settings tab**: configure refresh interval, rate limiting, IP allowlist, audit logging
6. Share the AI endpoint URL: `http://<your-ha-ip>:8100/api/`

## Access Levels

Each entity has one of three states:

| Level | AI Can See State | AI Can Call Services | Color |
|-------|-----------------|---------------------|-------|
| **Off** | No | No | Grey |
| **Read** | Yes | No | Blue |
| **Control** | Yes | Yes | Green |

Example: expose `sensor.front_door` as **read** (AI knows when door opens) but keep `lock.front_door` at **off** (AI cannot unlock it). Or set `light.office` to **control** so AI can turn it on/off.

## AI Endpoints (Port 8100)

### HA-Compatible Endpoints

These match Home Assistant's REST API format. OpenClaw can use standard HA client libraries.

| Endpoint | Description |
|----------|-------------|
| `GET /api/` | API health check |
| `GET /api/config` | Minimal config (exposed domains) |
| `GET /api/states` | All exposed entity states (read + control) |
| `GET /api/states/{entity_id}` | Single entity state (404 if not exposed) |
| `GET /api/services` | Services for domains with control entities |
| `POST /api/services/{domain}/{service}` | Call a service (control entities only) |

### Legacy Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/ai-sensors` | ClawBridge-format sensor data + access info |
| `POST /api/ai-action` | ClawBridge-format service call |

### Service Call Validation

When AI calls `POST /api/services/{domain}/{service}`:

1. Entity must be exposed with **control** access
2. Entity domain must match the URL domain
3. Request must pass rate limiting
4. Request IP must be in allowlist (if configured)
5. Action is logged to audit trail
6. If denied, returns 403 with explanation

### Example: Turn on office light

```
POST http://<ha-ip>:8100/api/services/light/turn_on
Content-Type: application/json

{"entity_id": "light.office", "brightness": 200}
```

## Security

- **Setup UI** is protected by Home Assistant ingress authentication
- **Read-only entities** cannot be controlled via the AI endpoint
- **Control entities** require explicit user selection (with confirmation for sensitive domains)
- **Rate limiting**: configurable requests/minute per IP (default 60)
- **IP allowlist**: optionally restrict which IPs can access port 8100
- **Audit logging**: all service calls (success + denied) logged to JSONL
- **Sensitive domain warnings**: lock, cover, alarm, climate, valve require explicit confirmation before granting control

## Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Refresh Interval | Seconds between state refreshes | 5 |
| Filter Unavailable | Exclude unavailable/unknown entities | On |
| Compact Mode | Minimal JSON in legacy endpoint | Off |
| Audit Logging | Log all AI service calls | On |
| Audit Retention | Days to keep audit logs | 30 |
| Rate Limit | Max service calls/minute per IP | 60 |
| IP Allowlist | Restrict port 8100 access (empty = all) | Empty |

## Features

- Per-entity read-only vs control access levels
- HA-compatible REST API (standard client libraries work)
- Audit logging with UI viewer
- Rate limiting and IP allowlist
- Sensitive domain warnings (lock, cover, alarm, climate, valve)
- Domain-based entity browsing with search
- Named presets with import/export
- Automatic config migration from older versions
