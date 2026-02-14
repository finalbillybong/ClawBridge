# ClawBridge

AI guard rail for Home Assistant. Exposes only the entities you choose, with per-entity access levels and comprehensive security controls.

## Installation

1. In Home Assistant, go to **Settings > Add-ons > Add-on Store**
2. Click the three dots menu (top right) > **Repositories**
3. Add this repository URL:
   ```
   https://github.com/finalbillybong/ClawBridge
   ```
4. Find **"ClawBridge"** in the add-on store and click **Install**
5. Start the add-on and open the Web UI

## What It Does

- **Guard rail** between your AI agent (OpenClaw) and Home Assistant
- Four-state per-entity access: **off** / **read** (AI sees state) / **confirm** (AI requests, human approves) / **control** (AI acts directly)
- HA-compatible REST API on port 8100 -- standard HA client libraries work out of the box
- WebSocket endpoint for real-time state change streaming
- Entity annotations so AI understands what devices are and where they are
- Parameter constraints to prevent extreme values (e.g., thermostat max 24°C)
- Multi-agent API keys with per-key entity scoping
- Time-based access schedules (e.g., AI can control lights 6am-11pm only)
- Human-in-the-loop confirmation with actionable Approve/Deny push notifications (iOS + Android)
- Customisable AI name in notifications (e.g., "OpenClaw wants to turn on Office Light")
- Smart read-only domain detection (sensors, binary sensors, etc. only get off/read)
- To-do list item access (AI can read item names, not just counts, via `todo.get_items`)
- State history endpoint for AI pattern recognition
- Audit logging and usage dashboard
- Rate limiting and IP allowlist

## AI Endpoint

Point your AI agent at:

```
http://<your-ha-ip>:8100/api/
```

No authentication required by default. See [OPENCLAW_API.md](clawbridge/OPENCLAW_API.md) for the full API reference.

## Setting Up Your AI (OpenClaw / Custom Agent)

To give your AI the ability to control Home Assistant through ClawBridge:

1. **Provide the API reference** -- Give your AI the [OPENCLAW_API.md](clawbridge/OPENCLAW_API.md) file so it understands the available endpoints, authentication, access levels, and usage examples.
2. **Generate an API key** -- In the ClawBridge UI, go to the **Security** tab and create an API key. Give this key to your AI so it can authenticate with `Authorization: Bearer <key>`.
3. **Ask your AI to create a Home Assistant skill** -- With the API docs and key, ask your AI to build a skill/plugin that connects to ClawBridge to read entity states and call services.

> **Tip:** You can scope each API key to specific entities and set per-key rate limits from the Security tab. This lets you give different agents different levels of access.

## Features

- Four-state entity access: off / read / confirm / control
- HA-compatible REST API (`/api/states`, `/api/services/{domain}/{service}`)
- WebSocket real-time streaming (`/api/websocket`)
- State history access (`/api/history/period/{timestamp}`)
- Entity annotations (descriptions for AI context)
- Parameter constraints with auto-clamping
- Multi-agent API keys with entity scoping
- Time-based access schedules
- Human-in-the-loop confirmation with actionable phone notifications
- Usage dashboard with analytics
- Domain-based entity browser with real-time search
- Audit log viewer with action history
- Per-IP and per-key rate limiting
- IP allowlist (optional)
- Named presets with import/export
- Sensitive domain warnings (lock, cover, alarm, climate, valve)
- Read-only domain filtering (sensor, binary_sensor, weather, etc.)
- To-do list support: read items, add, update, and remove via `todo.*` services
- Smart constraint editor (only shows parameters the entity supports)

## Security

- Only explicitly exposed entities are visible to AI
- Read-only entities cannot be controlled (403), but can use read-safe services like `todo.get_items`
- Confirm entities require human approval via phone notification (Approve/Deny buttons)
- Parameter constraints prevent extreme AI actions
- Time schedules restrict when AI can act
- API keys isolate different agents
- All service calls are audit-logged
- Rate limiting prevents abuse
- Optional IP allowlist restricts access

## Screenshots

*Coming soon*

## Support

Open an issue on [GitHub](https://github.com/finalbillybong/ClawBridge/issues).
