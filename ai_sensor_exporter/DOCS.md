# AI Sensor Exporter

Expose selected Home Assistant entity states via a simple, unauthenticated JSON endpoint for AI agents to consume.

## How It Works

This add-on provides two interfaces:

1. **Setup UI** — A web-based dashboard accessible through the Home Assistant sidebar. Use it to browse all your entities, select which ones to expose, and manage presets and settings.

2. **AI Endpoint** — A read-only, unauthenticated JSON API at `/api/ai-sensors` that returns the current state of your selected entities.

## Setup

1. Install the add-on from the repository
2. Start the add-on
3. Click **"Open Web UI"** in the sidebar (or find "AI Sensors" in the sidebar)
4. Browse domains in the left panel and check the entities you want to expose
5. Click **Save Configuration**
6. Share the AI endpoint URL with your AI agents

## AI Endpoint

### URL
```
http://<your-ha-ip>:8099/api/ai-sensors
```

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
  "total_sensors": 1
}
```

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
- **Search** — Real-time filtering across entity names and IDs
- **Bulk selection** — Select/deselect all entities in a domain
- **Presets** — Save and load named entity selections
- **Settings** — Configure refresh interval, unavailable filtering, compact mode
- **Export/Import** — Backup and restore your configuration

## Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Refresh Interval | How often sensor states are refreshed (1-60 seconds) | 5 |
| Filter Unavailable | Exclude sensors in "unavailable"/"unknown" state | On |
| Compact Mode | Return only entity_id + state (saves bandwidth) | Off |

## Security

- The setup UI is protected by Home Assistant's ingress authentication
- The AI endpoint is **read-only** — no control capabilities
- Only explicitly selected sensors are exposed
- No access to HA tokens or admin functions from the AI endpoint
