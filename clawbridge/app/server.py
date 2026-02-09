"""Main server for ClawBridge.

Runs an aiohttp web server with:
- Authenticated ingress UI at /
- Unauthenticated AI endpoint at /api/ai-sensors
"""

import asyncio
import json
import logging
import os
import sys

import aiohttp as aiohttp_client
from aiohttp import web

from config_manager import ConfigManager
from ha_client import HAClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("clawbridge")

# Globals
config_mgr = ConfigManager()
ha_client = HAClient()
ingress_url = ""  # Will be set at startup


async def fetch_ingress_url():
    """Fetch the ingress URL from the Supervisor API."""
    global ingress_url
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    try:
        async with aiohttp_client.ClientSession(
            headers={"Authorization": f"Bearer {token}"}
        ) as session:
            async with session.get("http://supervisor/addons/self/info") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    addon_data = data.get("data", {})
                    ingress_url = addon_data.get("ingress_url", "")
                    logger.info("Ingress URL from Supervisor: %s", ingress_url)
                else:
                    body = await resp.text()
                    logger.warning("Failed to get addon info: HTTP %d - %s", resp.status, body)
    except Exception as e:
        logger.warning("Failed to fetch ingress URL: %s", e)


# ──────────────────────────────────────────────
# UI Routes (authenticated via ingress)
# ──────────────────────────────────────────────

async def handle_index(request):
    """Serve the main setup UI with CSS/JS inlined."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")

    with open(os.path.join(static_dir, "index.html"), "r") as f:
        html = f.read()
    with open(os.path.join(static_dir, "style.css"), "r") as f:
        css = f.read()
    with open(os.path.join(static_dir, "app.js"), "r") as f:
        js = f.read()

    # Inline CSS and JS
    html = html.replace(
        '<link rel="stylesheet" href="{{INGRESS_PATH}}/static/style.css">',
        f"<style>{css}</style>"
    )
    html = html.replace(
        '<script src="{{INGRESS_PATH}}/static/app.js"></script>',
        f"<script>{js}</script>"
    )

    # Inject the ingress base path for API calls
    # Also try to detect from X-Ingress-Path header as fallback
    base_path = ingress_url.rstrip("/")
    if not base_path:
        base_path = request.headers.get("X-Ingress-Path", "")
    logger.debug("Serving index with base_path: %s", base_path)

    html = html.replace(
        "const BASE_PATH = window.location.pathname.replace(/\\/$/, '');",
        f"const BASE_PATH = '{base_path}';"
    )

    return web.Response(text=html, content_type="text/html")


async def handle_static(request):
    """Serve static files (fallback)."""
    filename = request.match_info.get("filename", "")
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    filepath = os.path.join(static_dir, filename)

    if not os.path.exists(filepath):
        raise web.HTTPNotFound()

    content_types = {
        ".css": "text/css",
        ".js": "application/javascript",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
    }
    ext = os.path.splitext(filename)[1]
    content_type = content_types.get(ext, "application/octet-stream")

    with open(filepath, "r" if ext in (".css", ".js", ".svg") else "rb") as f:
        content = f.read()

    return web.Response(
        body=content if isinstance(content, bytes) else None,
        text=content if isinstance(content, str) else None,
        content_type=content_type,
    )


# ──────────────────────────────────────────────
# API Routes (authenticated - setup)
# ──────────────────────────────────────────────

async def api_get_entities(request):
    """Return all available entities grouped by domain."""
    domains = ha_client.get_all_entities()
    selected = config_mgr.selected_entities
    return web.json_response({
        "domains": domains,
        "selected": selected,
    })


async def api_save_selection(request):
    """Save the entity selection."""
    data = await request.json()
    entities = data.get("entities", [])
    config_mgr.selected_entities = entities
    return web.json_response({"status": "ok", "count": len(entities)})


async def api_get_settings(request):
    """Return current settings."""
    return web.json_response({
        "refresh_interval": config_mgr.refresh_interval,
        "filter_unavailable": config_mgr.filter_unavailable,
        "compact_mode": config_mgr.compact_mode,
    })


async def api_save_settings(request):
    """Save settings."""
    data = await request.json()
    if "refresh_interval" in data:
        config_mgr.refresh_interval = data["refresh_interval"]
    if "filter_unavailable" in data:
        config_mgr.filter_unavailable = data["filter_unavailable"]
    if "compact_mode" in data:
        config_mgr.compact_mode = data["compact_mode"]
    return web.json_response({"status": "ok"})


async def api_get_presets(request):
    """Return all saved presets."""
    return web.json_response({"presets": config_mgr.presets})


async def api_save_preset(request):
    """Save a new preset."""
    data = await request.json()
    name = data.get("name", "")
    entities = data.get("entities", [])
    if not name:
        return web.json_response({"error": "Preset name required"}, status=400)
    config_mgr.save_preset(name, entities)
    return web.json_response({"status": "ok"})


async def api_delete_preset(request):
    """Delete a preset."""
    name = request.match_info.get("name", "")
    if config_mgr.delete_preset(name):
        return web.json_response({"status": "ok"})
    return web.json_response({"error": "Preset not found"}, status=404)


async def api_load_preset(request):
    """Load a preset's entity list."""
    name = request.match_info.get("name", "")
    entities = config_mgr.load_preset(name)
    if entities is not None:
        return web.json_response({"entities": entities})
    return web.json_response({"error": "Preset not found"}, status=404)


async def api_export_config(request):
    """Export full config for backup."""
    return web.json_response(config_mgr.export_config())


async def api_import_config(request):
    """Import config from backup."""
    data = await request.json()
    config_mgr.import_config(data)
    return web.json_response({"status": "ok"})


# ──────────────────────────────────────────────
# AI Endpoint (unauthenticated, read-only)
# ──────────────────────────────────────────────

async def api_ai_sensors(request):
    """Public endpoint for AI agents to scrape sensor data."""
    data = await ha_client.get_exposed_data(
        config_mgr.selected_entities,
        filter_unavailable=config_mgr.filter_unavailable,
        compact=config_mgr.compact_mode,
    )
    return web.json_response(data, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache",
    })


# ──────────────────────────────────────────────
# App Setup
# ──────────────────────────────────────────────

async def on_startup(app):
    """Start HA client and background refresh on app startup."""
    # Fetch ingress URL from Supervisor
    await fetch_ingress_url()

    await ha_client.start()
    app["refresh_task"] = asyncio.create_task(
        ha_client.periodic_refresh(config_mgr.refresh_interval)
    )
    logger.info("ClawBridge started")


async def on_cleanup(app):
    """Clean up on shutdown."""
    if "refresh_task" in app:
        app["refresh_task"].cancel()
    await ha_client.stop()
    logger.info("ClawBridge stopped")


def create_ingress_app():
    """Create the ingress app (authenticated UI + setup APIs)."""
    app = web.Application()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    # Ingress UI routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/static/{filename}", handle_static)

    # Setup API routes (behind ingress auth)
    app.router.add_get("/api/entities", api_get_entities)
    app.router.add_post("/api/selection", api_save_selection)
    app.router.add_get("/api/settings", api_get_settings)
    app.router.add_post("/api/settings", api_save_settings)
    app.router.add_get("/api/presets", api_get_presets)
    app.router.add_post("/api/presets", api_save_preset)
    app.router.add_delete("/api/presets/{name}", api_delete_preset)
    app.router.add_get("/api/presets/{name}", api_load_preset)
    app.router.add_get("/api/config/export", api_export_config)
    app.router.add_post("/api/config/import", api_import_config)

    # Also serve AI endpoint on ingress for testing
    app.router.add_get("/api/ai-sensors", api_ai_sensors)

    return app


def create_public_app():
    """Create the public app (AI endpoint only, no auth required)."""
    app = web.Application()

    # Only the read-only AI endpoint
    app.router.add_get("/api/ai-sensors", api_ai_sensors)
    app.router.add_get("/", api_ai_sensors)  # Also serve at root for convenience

    return app


async def start_servers():
    """Start both the ingress server and the public AI endpoint server."""
    ingress_port = int(os.environ.get("INGRESS_PORT", 8099))
    public_port = 8100

    # Create both apps
    ingress_app = create_ingress_app()
    public_app = create_public_app()

    # Start ingress server
    ingress_runner = web.AppRunner(ingress_app)
    await ingress_runner.setup()
    ingress_site = web.TCPSite(ingress_runner, "0.0.0.0", ingress_port)
    await ingress_site.start()
    logger.info("Ingress server started on port %d", ingress_port)

    # Start public AI endpoint server
    public_runner = web.AppRunner(public_app)
    await public_runner.setup()
    public_site = web.TCPSite(public_runner, "0.0.0.0", public_port)
    await public_site.start()
    logger.info("Public AI endpoint started on port %d", public_port)
    logger.info("AI agents can fetch: http://<your-ha-ip>:%d/api/ai-sensors", public_port)

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await ingress_runner.cleanup()
        await public_runner.cleanup()


if __name__ == "__main__":
    logger.info("Starting ClawBridge servers...")
    asyncio.run(start_servers())
