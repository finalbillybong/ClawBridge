# Changelog

## 1.4.2 - Sidebar Icon Fix

- **Fix**: Sidebar icon was blank — `mdi:crab` does not exist in MDI. Changed to `mdi:zodiac-cancer` (crab symbol)

## 1.4.1 - Unified Branding

- **Branding**: New lobster claw + bridge logo applied consistently across all touchpoints
- **Web UI**: Two-tone sidebar icon (coral claw, blue bridge) replaces old abstract bridge SVG
- **Add-on store**: New `icon.png` (128x128) and `logo.png` with matching claw+bridge design
- **Favicon**: SVG favicon added to browser tab using the same two-tone mark
- **Sidebar**: Changed `panel_icon` from `mdi:bridge` to `mdi:crab` (closer to lobster/claw concept)
- **Source**: Master SVG at `clawbridge/app/static/logo.svg`

## 1.4.0 - AI Context Endpoint

- **Feature**: New `GET /api/context` endpoint returns a complete summary of the AI's permissions, exposed entities (grouped by access level), annotations, parameter constraints, time schedules, available services, and human-readable limitations -- all in a single call
- **Token-efficient**: Designed for the "hybrid approach" -- static rules live in OPENCLAW_API.md (ingested once), dynamic context (current entities, constraints, schedules) comes from this endpoint

## 1.3.2 - To-Do List Item Access Fix

- **Fix**: `todo.get_items` now works correctly — HA requires `return_response` as a URL query parameter (`?return_response`), not in the JSON body. Previous version returned HTTP 400.
- **Fix**: `ha_client.call_service()` now accepts a `return_response` flag to append `?return_response` to the HA API URL

## 1.3.1 - To-Do List Item Access

- **Feature**: AI can now read individual to-do list items (names, statuses) via `todo.get_items`, not just the item count
- **Improvement**: Added read-safe service allowlist — `todo.get_items` works even with `read` access since it only returns data
- **Docs**: Updated `OPENCLAW_API.md` with `todo.get_items` usage example and response format

## 1.3.0 - Light Mode & AI Chat

- **Light mode**: Toggle between dark and light themes via the sun/moon button in the sidebar header; preference saved in localStorage
- **AI Chat tab**: Talk directly to your AI from the ClawBridge UI with real-time streaming responses
  - Streaming SSE proxy to OpenClaw Gateway `/v1/chat/completions`
  - Server-side chat history persistence (capped at 200 messages)
  - Markdown rendering (code blocks, inline code, bold, italic)
  - New conversation / clear history button
  - Mobile-friendly full-height chat layout
- **Gateway settings**: Configure Gateway URL and auth token in the Settings tab with a connection test button
- **New endpoints**: `POST /api/chat`, `GET/POST/DELETE /api/chat/history`, `GET /api/chat/status` (all on authenticated ingress port)

## 1.2.5 - Mobile Responsive UI

- **Mobile layout**: Full responsive redesign for phones and tablets
- **Collapsible sidebar**: Hamburger menu toggles sidebar as slide-in overlay on mobile, closes on domain select and save
- **Stacked entity cards**: Access toggle moves to full-width row above entity info on narrow screens
- **Larger tap targets**: All buttons, access toggles, and tabs meet 44px minimum touch target guidelines
- **Icon-only tabs**: Tab labels hidden on mobile, icons enlarged for easy navigation
- **Full-width settings**: Input fields and setting rows stack vertically on mobile
- **Simplified status dock**: Shows only read/confirm/control counts on mobile
- **Touch-friendly actions**: Entity action buttons (annotate, constraints) always visible on touch devices
- **Scrollable modals**: Modals cap at 85vh with scroll for tall content on short screens

## 1.2.4 - Read-Only Domain UX

- **Improvement**: Hide "ask" and "ctrl" buttons for read-only domains (sensor, binary_sensor, weather, sun, zone, person, device_tracker, geo_location, air_quality, image) since they have no controllable services
- **Guard**: Programmatic block on setting confirm/control access for read-only domains

## 1.2.3 - WebSocket Fix

- **Fix**: WebSocket connections crashed immediately after auth due to unhashable `set` inside a `set` container (`TypeError: unhashable type: 'set'`). Changed `_ws_clients` from `set` to `list` so real-time state streaming now works correctly.

## 1.2.2 - Smart Constraints & Branding

- **Improvement**: Constraint parameter editor now only shows parameters the entity actually supports (e.g., no brightness slider for on/off-only lights)
- **Branding**: Replaced "air gap" terminology with "guard rail" across all documentation and UI

## 1.2.1 - Security & UI Fix

- **Fix**: API key authentication now enforced on legacy `/api/ai-action` endpoint (previously bypassed entirely)
- **Fix**: Tab content panels (settings, security, etc.) now scroll correctly
- **Fix**: Added `Cache-Control: no-store` headers to prevent browser from serving stale cached UI

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

## 1.1.0 - Guard Rail Release

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
