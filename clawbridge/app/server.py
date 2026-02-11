"""Main server for ClawBridge.

Runs an aiohttp web server with:
- Authenticated ingress UI at / (port 8099)
- Unauthenticated AI endpoints at port 8100 (HA-compatible + legacy)
"""

import asyncio
import json
import logging
import os
import sys
import time

import aiohttp as aiohttp_client
from aiohttp import web

from config_manager import ConfigManager
from ha_client import HAClient
from audit_logger import AuditLogger

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
audit_logger = AuditLogger()
ingress_url = ""  # Will be set at startup

# Rate limiting: per-IP token bucket
_rate_buckets = {}  # ip -> { tokens, last_refill }


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
# Security Middleware
# ──────────────────────────────────────────────

def _get_client_ip(request):
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    peername = request.transport.get_extra_info("peername")
    if peername:
        return peername[0]
    return "unknown"


def _check_rate_limit(ip):
    """Token bucket rate limiter. Returns True if allowed, False if exceeded."""
    limit = config_mgr.rate_limit_per_minute
    now = time.time()

    if ip not in _rate_buckets:
        _rate_buckets[ip] = {"tokens": limit, "last_refill": now}

    bucket = _rate_buckets[ip]
    elapsed = now - bucket["last_refill"]
    bucket["tokens"] = min(limit, bucket["tokens"] + elapsed * (limit / 60.0))
    bucket["last_refill"] = now

    if bucket["tokens"] >= 1:
        bucket["tokens"] -= 1
        return True
    return False


def _check_ip_allowlist(ip):
    """Check if IP is in allowlist (empty list = allow all)."""
    allowed = config_mgr.allowed_ips
    if not allowed:
        return True
    return ip in allowed


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Cache-Control": "no-cache",
}


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

    html = html.replace(
        '<link rel="stylesheet" href="{{INGRESS_PATH}}/static/style.css">',
        f"<style>{css}</style>"
    )
    html = html.replace(
        '<script src="{{INGRESS_PATH}}/static/app.js"></script>',
        f"<script>{js}</script>"
    )

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
# Setup API Routes (authenticated - UI)
# ──────────────────────────────────────────────

async def api_get_entities(request):
    """Return all available entities grouped by domain."""
    domains = ha_client.get_all_entities()
    exposed = config_mgr.exposed_entities
    return web.json_response({
        "domains": domains,
        "exposed_entities": exposed,
    })


async def api_save_selection(request):
    """Save the entity selection (unified exposed_entities dict)."""
    data = await request.json()
    exposed = data.get("exposed_entities")
    if exposed is not None and isinstance(exposed, dict):
        config_mgr.exposed_entities = exposed
    else:
        # Legacy: accept simple list (sets all to "read")
        entities = data.get("entities", [])
        if entities:
            config_mgr.selected_entities = entities
    return web.json_response({"status": "ok", "count": len(config_mgr.exposed_entities)})


async def api_get_settings(request):
    """Return current settings."""
    return web.json_response({
        "refresh_interval": config_mgr.refresh_interval,
        "filter_unavailable": config_mgr.filter_unavailable,
        "compact_mode": config_mgr.compact_mode,
        "audit_enabled": config_mgr.audit_enabled,
        "audit_retention_days": config_mgr.audit_retention_days,
        "rate_limit_per_minute": config_mgr.rate_limit_per_minute,
        "allowed_ips": config_mgr.allowed_ips,
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
    if "audit_enabled" in data:
        config_mgr.audit_enabled = data["audit_enabled"]
    if "audit_retention_days" in data:
        config_mgr.audit_retention_days = data["audit_retention_days"]
    if "rate_limit_per_minute" in data:
        config_mgr.rate_limit_per_minute = data["rate_limit_per_minute"]
    if "allowed_ips" in data:
        config_mgr.allowed_ips = data["allowed_ips"]
    return web.json_response({"status": "ok"})


async def api_get_presets(request):
    """Return all saved presets."""
    return web.json_response({"presets": config_mgr.presets})


async def api_save_preset(request):
    """Save a new preset."""
    data = await request.json()
    name = data.get("name", "")
    entities = data.get("entities", {})
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


async def api_get_services(request):
    """Return available HA services (domain -> list of service names)."""
    services = await ha_client.get_services()
    return web.json_response({"services": services})


# ── Audit API (authenticated) ────────────────

async def api_get_audit_logs(request):
    """Return audit log entries with optional filters."""
    entity = request.query.get("entity")
    result = request.query.get("result")
    since = request.query.get("since")
    until = request.query.get("until")
    limit = int(request.query.get("limit", 200))
    logs = await audit_logger.get_logs(
        limit=limit, entity_filter=entity, result_filter=result,
        since=since, until=until,
    )
    return web.json_response({"logs": logs, "count": len(logs)})


async def api_clear_audit_logs(request):
    """Clear all audit logs."""
    await audit_logger.clear_logs()
    return web.json_response({"status": "ok"})


# ──────────────────────────────────────────────
# HA-Compatible Data Plane (port 8100, unauthenticated)
# ──────────────────────────────────────────────

async def ha_api_root(request):
    """GET /api/ - HA compatibility: API health check."""
    return web.json_response({"message": "API running."}, headers=CORS_HEADERS)


async def ha_api_config(request):
    """GET /api/config - HA compatibility: minimal mock config."""
    return web.json_response({
        "components": list(config_mgr.get_control_domains()),
        "version": "clawbridge-1.1.0",
        "location_name": "ClawBridge",
    }, headers=CORS_HEADERS)


async def ha_api_get_states(request):
    """GET /api/states - Return all exposed entities in HA state format."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    all_exposed = config_mgr.get_all_exposed_ids()
    states = ha_client.get_ha_format_states(
        all_exposed, filter_unavailable=config_mgr.filter_unavailable
    )
    return web.json_response(states, headers=CORS_HEADERS)


async def ha_api_get_state(request):
    """GET /api/states/{entity_id} - Return single entity if exposed, else 404."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    entity_id = request.match_info.get("entity_id", "")
    access = config_mgr.is_entity_exposed(entity_id)
    if not access:
        # Don't leak whether entity exists in HA
        return web.json_response(
            {"message": f"Entity not found: {entity_id}"}, status=404, headers=CORS_HEADERS
        )

    state = ha_client.get_ha_format_single(entity_id)
    if not state:
        return web.json_response(
            {"message": f"Entity not found: {entity_id}"}, status=404, headers=CORS_HEADERS
        )
    return web.json_response(state, headers=CORS_HEADERS)


async def ha_api_get_services(request):
    """GET /api/services - Return services only for domains with control entities."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    control_domains = config_mgr.get_control_domains()
    all_services = await ha_client.get_services()
    # Filter to only domains that have at least one control entity
    filtered = []
    for domain, services in all_services.items():
        if domain in control_domains:
            filtered.append({"domain": domain, "services": services})
    return web.json_response(filtered, headers=CORS_HEADERS)


async def ha_api_call_service(request):
    """POST /api/services/{domain}/{service} - HA-compatible service call with allowlist validation."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    if not _check_rate_limit(ip):
        await audit_logger.log_action(
            "service_call", source_ip=ip, result="rate_limited",
            domain=request.match_info.get("domain"),
            service=request.match_info.get("service"),
        )
        return web.json_response(
            {"message": "Rate limit exceeded. Try again later."}, status=429, headers=CORS_HEADERS
        )

    domain = request.match_info.get("domain", "")
    service = request.match_info.get("service", "")
    start_time = time.time()

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Extract entity_id(s) from body
    raw_entity = body.get("entity_id")
    entity_ids = []
    if isinstance(raw_entity, str):
        entity_ids = [raw_entity]
    elif isinstance(raw_entity, list):
        entity_ids = [e for e in raw_entity if isinstance(e, str)]

    # Validate each entity against allowlist
    for eid in entity_ids:
        access = config_mgr.is_entity_exposed(eid)
        if not access:
            await audit_logger.log_action(
                "service_call", entity_id=eid, domain=domain, service=service,
                source_ip=ip, result="denied", error="entity_not_exposed",
            )
            return web.json_response(
                {"message": f"Entity not exposed: {eid}"}, status=403, headers=CORS_HEADERS
            )
        if access != "control":
            await audit_logger.log_action(
                "service_call", entity_id=eid, domain=domain, service=service,
                source_ip=ip, result="denied", error="read_only_entity",
            )
            return web.json_response(
                {"message": f"Entity {eid} is read-only. Control access not granted."}, status=403, headers=CORS_HEADERS
            )
        # Verify domain matches
        eid_domain = eid.split(".")[0] if "." in eid else ""
        if eid_domain != domain:
            return web.json_response(
                {"message": f"Domain mismatch: {eid} is not in domain {domain}"}, status=400, headers=CORS_HEADERS
            )

    # If no entity specified, check that domain has control entities (some services don't need entity_id)
    if not entity_ids:
        control_domains = config_mgr.get_control_domains()
        if domain not in control_domains:
            await audit_logger.log_action(
                "service_call", domain=domain, service=service,
                source_ip=ip, result="denied", error="domain_not_exposed",
            )
            return web.json_response(
                {"message": f"No control entities exposed in domain {domain}"}, status=403, headers=CORS_HEADERS
            )

    # Proxy to Home Assistant
    ok, result = await ha_client.call_service(domain, service, body)
    elapsed_ms = int((time.time() - start_time) * 1000)

    if ok:
        await audit_logger.log_action(
            "service_call", entity_id=entity_ids[0] if entity_ids else None,
            domain=domain, service=service,
            parameters={k: v for k, v in body.items() if k != "entity_id"},
            source_ip=ip, result="success", response_time_ms=elapsed_ms,
        )
        return web.json_response(result, headers=CORS_HEADERS)
    else:
        await audit_logger.log_action(
            "service_call", entity_id=entity_ids[0] if entity_ids else None,
            domain=domain, service=service,
            source_ip=ip, result="error", error=str(result.get("error", "")),
            response_time_ms=elapsed_ms,
        )
        return web.json_response(
            {"message": result.get("error", "Service call failed")}, status=502, headers=CORS_HEADERS
        )


# ──────────────────────────────────────────────
# Legacy AI Endpoints (backward compatibility)
# ──────────────────────────────────────────────

async def api_ai_sensors(request):
    """GET /api/ai-sensors - Legacy endpoint: sensor data + allowed actions."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    all_exposed = config_mgr.get_all_exposed_ids()
    data = await ha_client.get_exposed_data(
        all_exposed,
        filter_unavailable=config_mgr.filter_unavailable,
        compact=config_mgr.compact_mode,
    )
    # Include access info so AI knows what it can read vs control
    exposed = config_mgr.exposed_entities
    data["entity_access"] = exposed
    data["controllable_entities"] = config_mgr.get_control_entity_ids()
    data["control_domains"] = list(config_mgr.get_control_domains())
    return web.json_response(data, headers=CORS_HEADERS)


async def api_ai_action(request):
    """POST /api/ai-action - Legacy endpoint for AI to call an allowed service."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"error": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    if not _check_rate_limit(ip):
        return web.json_response({"error": "Rate limit exceeded"}, status=429, headers=CORS_HEADERS)

    try:
        body = await request.json()
    except Exception as e:
        return web.json_response({"error": f"Invalid JSON: {e}"}, status=400)

    service_id = body.get("service") or body.get("service_id")
    if not service_id or "." not in service_id:
        return web.json_response({"error": "Missing or invalid 'service' (e.g. light.turn_on)"}, status=400)

    domain, service = service_id.split(".", 1)
    entity_id = body.get("entity_id")
    extra_data = body.get("data") or body.get("service_data") or {}
    start_time = time.time()

    # Validate entity access level
    if entity_id:
        access = config_mgr.is_entity_exposed(entity_id)
        if not access:
            await audit_logger.log_action(
                "service_call", entity_id=entity_id, domain=domain, service=service,
                source_ip=ip, result="denied", error="entity_not_exposed",
            )
            return web.json_response({"error": f"Entity {entity_id} is not exposed"}, status=403)
        if access != "control":
            await audit_logger.log_action(
                "service_call", entity_id=entity_id, domain=domain, service=service,
                source_ip=ip, result="denied", error="read_only_entity",
            )
            return web.json_response({"error": f"Entity {entity_id} is read-only"}, status=403)

    service_data = dict(extra_data)
    if entity_id:
        service_data["entity_id"] = entity_id

    ok, result = await ha_client.call_service(domain, service, service_data)
    elapsed_ms = int((time.time() - start_time) * 1000)

    if not ok:
        await audit_logger.log_action(
            "service_call", entity_id=entity_id, domain=domain, service=service,
            source_ip=ip, result="error", error=str(result.get("error", "")),
            response_time_ms=elapsed_ms,
        )
        return web.json_response({"error": result.get("error", "Service call failed")}, status=502)

    await audit_logger.log_action(
        "service_call", entity_id=entity_id, domain=domain, service=service,
        parameters={k: v for k, v in service_data.items() if k != "entity_id"},
        source_ip=ip, result="success", response_time_ms=elapsed_ms,
    )
    return web.json_response({"status": "ok", "result": result}, headers=CORS_HEADERS)


async def handle_options(request):
    """Handle CORS preflight requests."""
    return web.Response(headers=CORS_HEADERS)


# ──────────────────────────────────────────────
# App Setup
# ──────────────────────────────────────────────

async def on_startup(app):
    """Start HA client and background tasks on app startup."""
    await fetch_ingress_url()
    await ha_client.start()
    app["refresh_task"] = asyncio.create_task(
        ha_client.periodic_refresh(config_mgr.refresh_interval)
    )
    if config_mgr.audit_enabled:
        app["audit_cleanup_task"] = asyncio.create_task(
            audit_logger.periodic_cleanup(config_mgr.audit_retention_days)
        )
    logger.info("ClawBridge started")


async def on_cleanup(app):
    """Clean up on shutdown."""
    for task_name in ("refresh_task", "audit_cleanup_task"):
        if task_name in app:
            app[task_name].cancel()
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
    app.router.add_get("/api/services", api_get_services)

    # Audit
    app.router.add_get("/api/audit/logs", api_get_audit_logs)
    app.router.add_delete("/api/audit/logs", api_clear_audit_logs)

    # Also serve AI endpoints on ingress for testing
    app.router.add_get("/api/ai-sensors", api_ai_sensors)
    app.router.add_post("/api/ai-action", api_ai_action)

    return app


def create_public_app():
    """Create the public app (HA-compatible + legacy AI endpoints, no auth required)."""
    app = web.Application()

    # HA-compatible endpoints
    app.router.add_get("/api/", ha_api_root)
    app.router.add_get("/api/config", ha_api_config)
    app.router.add_get("/api/states", ha_api_get_states)
    app.router.add_get("/api/states/{entity_id}", ha_api_get_state)
    app.router.add_get("/api/services", ha_api_get_services)
    app.router.add_post("/api/services/{domain}/{service}", ha_api_call_service)

    # Legacy endpoints
    app.router.add_get("/api/ai-sensors", api_ai_sensors)
    app.router.add_get("/", api_ai_sensors)
    app.router.add_post("/api/ai-action", api_ai_action)

    # CORS preflight
    app.router.add_route("OPTIONS", "/{path:.*}", handle_options)

    return app


async def start_servers():
    """Start both the ingress server and the public AI endpoint server."""
    ingress_port = int(os.environ.get("INGRESS_PORT", 8099))
    public_port = 8100

    ingress_app = create_ingress_app()
    public_app = create_public_app()

    ingress_runner = web.AppRunner(ingress_app)
    await ingress_runner.setup()
    ingress_site = web.TCPSite(ingress_runner, "0.0.0.0", ingress_port)
    await ingress_site.start()
    logger.info("Ingress server started on port %d", ingress_port)

    public_runner = web.AppRunner(public_app)
    await public_runner.setup()
    public_site = web.TCPSite(public_runner, "0.0.0.0", public_port)
    await public_site.start()
    logger.info("Public AI endpoint started on port %d", public_port)
    logger.info("HA-compatible API: http://<your-ha-ip>:%d/api/", public_port)

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
