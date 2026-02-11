# Changelog

## 1.2.0 - Feature Expansion Release

- **Four-state entity access**: off / read / confirm / control — confirm entities require human approval via HA notification
- **Entity annotations**: User-written descriptions visible to AI (context for ambiguous entities)
- **Parameter constraints**: Min/max limits on service call parameters with auto-clamping
- **Multi-agent API keys**: Optional Bearer auth, per-key entity scoping, per-key rate limiting
- **Time-based access schedules**: Named schedules assigned to entities to restrict control hours
- **Human-in-the-loop confirmation**: Confirm entities return 202 Accepted; HA notification for approval
- **WebSocket real-time state streaming**: State changes pushed to connected AI clients
- **State history endpoint**: Proxy HA history API, filtered to exposed entities
- **Usage dashboard**: Stats cards, hourly chart, top entities analytics
- **Modern 2026 UI redesign**: Glassmorphism, bottom status dock, SVG icons
- **Security tab**: API keys management, schedules, pending approvals view

## 1.1.1 - Security Patch

- **Fix**: Prevent domain-wide wildcard attacks -- service calls without an `entity_id` now only target explicitly allowed control entities instead of all entities in the domain
- **Fix**: Harden IP detection to prefer socket peer IP over spoofable `X-Forwarded-For` header

## 1.1.0 - Air Gap Release

- **Per-entity access control**: three-state toggle (off / read / control) for each entity
- **HA-compatible REST API** on port 8100: `GET /api/states`, `GET /api/states/{id}`, `POST /api/services/{domain}/{service}`, `GET /api/services` -- standard HA client libraries work out of the box
- **Audit logging**: all AI service calls (success + denied) logged to JSONL with Audit tab viewer
- **Rate limiting**: configurable per-IP requests/minute on service call endpoints
- **IP allowlist**: optionally restrict which IPs can access port 8100
- **Sensitive domain warnings**: lock, cover, alarm_control_panel, climate, valve require explicit confirmation before granting control access
- **Automatic migration** from old config format (selected_entities + exposed_actions)
- **Legacy endpoint support**: `/api/ai-sensors` and `/api/ai-action` still work
- New OpenClaw API reference document (`OPENCLAW_API.md`)
- Sidebar shows read/control count breakdown
- Settings panel with audit, rate limit, and IP allowlist controls

## 1.0.7

- Redesigned UI with OpenClaw-inspired dark aesthetic
- New bold coral/teal color palette with terminal-style typography
- Redesigned logo and icon (claw + bridge motif)
- Monospace code-style accents throughout
- Cleaner sidebar, toolbar, and entity cards
- Improved status bar and toast notifications

## 1.0.0

- Initial release
- Domain-based entity browser with search
- Unauthenticated AI endpoint at `/api/ai-sensors`
- Preset management (save/load/delete)
- Settings: refresh interval, filter unavailable, compact mode
- Export/Import configuration
- Live entity state display
