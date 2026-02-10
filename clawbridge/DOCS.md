# ClawBridge

Bridge your Home Assistant sensors to AI agents via a simple, unauthenticated JSON endpoint.

## How It Works

This add-on provides two interfaces:

1. **Setup UI** — A web-based dashboard accessible through the Home Assistant sidebar. Use it to browse all your entities, select which ones to expose, and manage presets and settings.

2. **AI Endpoints** — Unauthenticated JSON APIs for AI agents:
   - **GET `/api/ai-sensors`** — Returns the current state of your selected entities plus the list of **allowed actions** (services/entities you exposed).
   - **POST `/api/ai-action`** — Lets the AI call only the Home Assistant services you exposed, on only the entities you chose (e.g. turn office light on/off only).

## Setup

1. Install the add-on from the repository
2. Start the add-on
3. Click **"Open Web UI"** in the sidebar (or find "ClawBridge" in the sidebar)
4. **Entities** tab: browse domains and check the entities you want to expose (sensor data)
5. **Actions** tab (optional): choose which services the AI can call and on which entities (e.g. `light.turn_on` / `light.turn_off` only for `light.office`)
6. Click **Save** / **Save actions**
7. Share the AI endpoint URLs with your AI agents

## AI Endpoint

### URL (public, no auth — use port 8100)
```
http://<your-ha-ip>:8100/api/ai-sensors
```

The response also includes an **`actions`** object: each key is a service (e.g. `light.turn_on`), each value is the list of entity IDs the AI may target. The AI should only call services/entities listed here.

### Response Format (Full)
```json
{
  "sensors": [
    {
      "entity_id": "sensor.living_room_temperature",
      "friendly_name": "Living Room Temperature",
      "state": "21.5",
      "last_state": "21.3",
      "last_changed": "2026-02-09T15:30:00Z",
      "unit_of_measurement": "°C",
      "device_class": "temperature",
      "area": "Living Room",
      "attributes": {
        "battery_level": 85
      }
    }
  ],
  "last_updated": "2026-02-09T15:37:00Z",
  "total_sensors": 1,
  "actions": {
    "light.turn_on": ["light.office"],
    "light.turn_off": ["light.office"]
  }
}
```

### Calling an action (POST /api/ai-action)

The AI can perform only the services you exposed, on only the entities you selected.

**URL:** `POST http://<your-ha-ip>:8100/api/ai-action`

**Body (JSON):**
```json
{
  "service": "light.turn_on",
  "entity_id": "light.office",
  "data": {}
}
```

- `service` — Required. Full service name, e.g. `light.turn_on`, `switch.turn_off`, `camera.disable_motion_detection`.
- `entity_id` — Optional for some services (e.g. `notify.notify`). When required, must be one of the entity IDs you exposed for that service.
- `data` — Optional. Extra service data (e.g. `brightness`, `rgb_color` for lights).

If the service or entity is not in your exposed actions list, the request returns 403.

### Response Format (Compact Mode)
```json
{
  "sensors": [
    {
      "entity_id": "sensor.living_room_temperature",
      "state": "21.5"
    }
  ],
  "last_updated": "2026-02-09T15:37:00Z",
  "total_sensors": 1
}
```

## Features

- **Domain-based browsing** — Entities organized by domain (sensor, light, switch, etc.)
- **Exposed actions** — Choose which services the AI can call and on which entities (e.g. only office light on/off; optionally cameras, switches, etc.)
- **Search** — Real-time filtering across entity names and IDs
- **Bulk selection** — Select/deselect all entities in a domain
- **Presets** — Save and load named entity selections
- **Settings** — Configure refresh interval, unavailable filtering, compact mode
- **Export/Import** — Backup and restore your configuration (includes exposed actions)

## Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Refresh Interval | How often sensor states are refreshed (1-60 seconds) | 5 |
| Filter Unavailable | Exclude sensors in "unavailable"/"unknown" state | On |
| Compact Mode | Return only entity_id + state (saves bandwidth) | Off |

## Security

- The setup UI is protected by Home Assistant's ingress authentication
- **GET /api/ai-sensors** is read-only (sensor data + list of allowed actions)
- **POST /api/ai-action** can only call services and entity IDs you explicitly exposed in the **Actions** tab
- No access to HA tokens or admin functions from the AI endpoints
