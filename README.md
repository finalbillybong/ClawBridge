# ClawBridge - AI Sensor Exporter for Home Assistant

A Home Assistant add-on that exposes selected entity states via a simple JSON endpoint for AI agent scraping.

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the three dots menu (top right) → **Repositories**
3. Add this repository URL:
   ```
   https://github.com/finalbillybong/ClawBridge
   ```
4. Find **"AI Sensor Exporter"** in the add-on store and click **Install**
5. Start the add-on and open the Web UI

## What It Does

- Provides a clean UI to browse and select which Home Assistant entities to expose
- Serves selected entity data as JSON at `/api/ai-sensors` (no authentication required)
- Perfect for AI agents, dashboards, or custom integrations that need read-only sensor access

## AI Endpoint

Once configured, your AI agents can fetch sensor data from:

```
http://<your-ha-ip>:8099/api/ai-sensors
```

No authentication required. Read-only. Only exposes entities you explicitly select.

## Features

- Domain-based entity browser
- Real-time search and filtering
- Bulk select/deselect per domain
- Named presets (e.g. "Weather", "Security", "Energy")
- Configurable refresh interval (1-60s)
- Filter out unavailable/unknown entities
- Compact mode for minimal JSON
- Export/Import configuration

## Screenshots

*Coming soon*

## Support

Open an issue on [GitHub](https://github.com/finalbillybong/ClawBridge/issues).
