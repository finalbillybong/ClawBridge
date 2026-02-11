# ClawBridge

Bidirectional air gap between AI agents and Home Assistant. Exposes only the entities you choose, with per-entity read-only vs control access levels.

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

- **Air gap** between your AI agent (OpenClaw) and Home Assistant
- Per-entity access control: **read-only** (AI can see state) or **control** (AI can see + call services)
- HA-compatible REST API on port 8100 -- standard HA client libraries work out of the box
- Audit logging of all AI service calls
- Rate limiting and IP allowlist for security
- Sensitive domain warnings (lock, cover, alarm, climate)

## AI Endpoint

Point your AI agent at:

```
http://<your-ha-ip>:8100/api/
```

No authentication required. See [OPENCLAW_API.md](clawbridge/OPENCLAW_API.md) for the full API reference.

## Features

- Three-state entity access: off / read / control
- HA-compatible REST API (`/api/states`, `/api/services/{domain}/{service}`)
- Domain-based entity browser with real-time search
- Audit log viewer with action history
- Per-IP rate limiting (configurable)
- IP allowlist (optional)
- Named presets with import/export
- Automatic migration from older config format

## Security

- Only explicitly exposed entities are visible to AI
- Read-only entities cannot be controlled (403)
- Sensitive domains require confirmation before granting control
- All service calls are audit-logged
- Rate limiting prevents abuse
- Optional IP allowlist restricts access

## Screenshots

*Coming soon*

## Support

Open an issue on [GitHub](https://github.com/finalbillybong/ClawBridge/issues).
