# ClawBridge

AI guard rail for Home Assistant. Sits between your AI agent and Home Assistant, exposing only the entities you choose with per-entity access control and comprehensive security.

## How It Works

Without ClawBridge, AI agents (via ha-mcp, custom skills, or direct API access) get broad access to your entire Home Assistant instance. ClawBridge acts as a **controlled proxy** — your AI connects to ClawBridge instead of directly to HA, and ClawBridge enforces per-entity permissions, rate limits, and audit logging.

```
┌──────────┐        ┌─────────────┐        ┌──────────────────┐
│ OpenClaw │ ──────▶│ ClawBridge  │ ──────▶│ Home Assistant   │
│ (or any  │  :8100 │ (guard rail)│  HA API│ (full access)    │
│  AI)     │◀────── │             │◀────── │                  │
└──────────┘        └─────────────┘        └──────────────────┘
                     Only exposes            Has all entities
                     selected entities       and services
                     with access levels
```

### ClawBridge vs HA MCP / ha-mcp

| Feature | HA MCP / ha-mcp | ClawBridge |
|---------|----------------|------------|
| Entity filtering | On/off per entity | **Four-state**: off / read / confirm / control |
| Human-in-the-loop | No | **Approve/Deny push notifications** for confirm-level entities |
| Parameter constraints | No | **Min/max limits** with auto-clamping (e.g., thermostat max 24°C) |
| Time-based schedules | No | **Restrict when AI can act** (e.g., lights only 6am-11pm) |
| Per-agent API keys | Single HA token | **Multiple keys** with per-key entity scoping and rate limits |
| Audit logging | No | **Full action log** with dashboard analytics |
| Rate limiting | No | **Per-IP and per-key** |
| Entity annotations | No | **Descriptions visible to AI** for context |
| Entity groups | No | **Bulk access control** by room/function |

## Installation

1. In Home Assistant, go to **Settings > Add-ons > Add-on Store**
2. Click the three dots menu (top right) > **Repositories**
3. Add this repository URL:
   ```
   https://github.com/finalbillybong/ClawBridge
   ```
4. Find **"ClawBridge"** in the add-on store and click **Install**
5. Start the add-on and open the Web UI

## Quick Start

### 1. Expose entities

Open the ClawBridge Web UI (from the HA sidebar or add-on page). Browse your entities by domain and set access levels:

- **off** — Hidden from AI entirely
- **read** — AI can see state but not control
- **confirm** — AI requests action, you approve/deny via phone notification
- **control** — AI acts directly

Click **Save** when done.

### 2. Add annotations (recommended)

Click the pencil icon on any entity to add a description (e.g., "Main ceiling light in the home office, 2nd floor"). These descriptions are returned in API responses so the AI understands what devices are and where they are.

### 3. Create an API key (recommended)

Go to the **Security** tab and create an API key. Each key can be scoped to specific entities with its own rate limit — useful if you run multiple AI agents.

### 4. Connect your AI

Point your AI agent at ClawBridge instead of directly at Home Assistant:

```
http://<your-ha-ip>:8100/api/
```

Give your AI the [OPENCLAW_API.md](clawbridge/OPENCLAW_API.md) file so it understands the available endpoints. The AI should call `GET /api/context` first to discover its permissions and available entities.

If using an API key, the AI authenticates with: `Authorization: Bearer cb_xxxx`

### 5. Verify

Check the **Audit** tab in the ClawBridge UI to see your AI's requests. The **Dashboard** tab shows usage stats.

## Migrating from ha-mcp

If you're currently using ha-mcp to give OpenClaw access to Home Assistant:

1. **Install ClawBridge** using the steps above
2. **Expose entities** — Select which entities the AI should see and set access levels. ClawBridge starts with everything hidden, so you explicitly opt in.
3. **Update your AI's configuration** — Instead of connecting via MCP to Home Assistant directly, point your AI at `http://<ha-ip>:8100`. Give it the [OPENCLAW_API.md](clawbridge/OPENCLAW_API.md) reference doc and an API key.
4. **Remove or disable ha-mcp** — Once ClawBridge is handling all AI access, you no longer need ha-mcp. ClawBridge provides a standard HA-compatible REST API, so any AI that works with the HA API will work with ClawBridge out of the box.

> **Why switch?** ha-mcp gives the AI access to everything you've exposed in HA's built-in entity filter with no granularity beyond on/off. ClawBridge adds read/confirm/control per entity, parameter constraints (e.g., thermostat max 24°C), time schedules, human-in-the-loop approval, per-agent API keys, and a full audit trail.

## Features

- **Four-state entity access:** off / read / confirm / control
- **HA-compatible REST API** on port 8100 (`/api/states`, `/api/services/{domain}/{service}`) — standard HA client libraries work out of the box
- **WebSocket real-time streaming** (`/api/websocket`) — state changes pushed to connected AI clients
- **AI context endpoint** (`/api/context`) — single call returns all permissions, entities, constraints, and schedules
- **State history** (`/api/history/period/{timestamp}`) — for AI pattern recognition
- **Entity annotations** — user-written descriptions visible to AI for context
- **Parameter constraints** — min/max limits with auto-clamping (e.g., brightness 1-200)
- **Multi-agent API keys** — per-key entity scoping and rate limits
- **Time-based access schedules** — restrict when AI can control entities (e.g., 6am-11pm only)
- **Human-in-the-loop confirmation** — confirm-level entities trigger Approve/Deny push notifications (iOS + Android)
- **Entity groups** — organise entities by room/function for bulk access control
- **Usage dashboard** with hourly charts, top entities, and action counts
- **Audit logging** — all AI service calls logged with full action history
- **Rate limiting** — per-IP and per-key
- **IP allowlist** — optionally restrict which IPs can access port 8100
- **Named presets** with import/export
- **Sensitive domain warnings** — lock, cover, alarm, climate, valve require explicit confirmation
- **Read-only domain detection** — sensor, binary_sensor, weather, etc. only get off/read
- **To-do list support** — read items via `todo.get_items` (works with read access), modify with confirm/control

## Security

- Only explicitly exposed entities are visible to AI — everything else is hidden
- Read-only entities cannot be controlled (returns 403)
- Confirm entities require human approval via phone notification (Approve/Deny buttons)
- Parameter constraints prevent extreme AI actions (values auto-clamped)
- Time schedules restrict when AI can act
- API keys isolate different agents with per-key entity scoping
- All service calls are audit-logged
- Rate limiting prevents abuse
- Optional IP allowlist restricts network access

## API Reference

See [OPENCLAW_API.md](clawbridge/OPENCLAW_API.md) for the full endpoint documentation with examples.

## Support

Open an issue on [GitHub](https://github.com/finalbillybong/ClawBridge/issues).
