"""Main server for ClawBridge.

Runs an aiohttp web server with:
- Authenticated ingress UI at / (port 8099)
- Unauthenticated AI endpoints at port 8100 (HA-compatible + legacy)
- WebSocket endpoint for real-time state change streaming
"""

import asyncio
import json
import logging
import os
import sys
import time
import secrets

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

# Pending confirmation actions: { action_id: { domain, service, entity_id, data, timestamp, status, source_ip } }
_pending_actions = {}

# WebSocket clients: list of (ws, subscribed_entity_ids_set)
_ws_clients = []


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
    """Extract client IP from request. Prefer socket IP to prevent X-Forwarded-For spoofing."""
    peername = request.transport.get_extra_info("peername")
    if peername:
        return peername[0]
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return "unknown"


def _check_rate_limit(ip, custom_limit=None):
    """Token bucket rate limiter. Returns True if allowed, False if exceeded."""
    limit = custom_limit or config_mgr.rate_limit_per_minute
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


def _check_api_key(request):
    """Check API key if keys are configured. Returns (key_id, key_config) or (None, None).
    If no keys configured, returns ('__public__', None) to indicate open access.
    """
    keys = config_mgr.api_keys
    if not keys:
        return "__public__", None  # No keys configured = open access

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        key_id, key_config = config_mgr.get_key_by_token(token)
        if key_id:
            return key_id, key_config
    return None, None


def _get_effective_entities(key_config):
    """Get the effective entity access dict for an API key.
    If key has its own entities, intersect with global. Otherwise use global.
    """
    global_entities = config_mgr.exposed_entities
    if not key_config:
        return global_entities
    key_entities = key_config.get("entities", {})
    if not key_entities:
        return global_entities
    # Intersect: key can only access entities that are also globally exposed
    result = {}
    for eid, key_access in key_entities.items():
        global_access = global_entities.get(eid)
        if global_access:
            # Take the more restrictive access level
            levels = {"read": 0, "confirm": 1, "control": 2}
            min_level = min(levels.get(key_access, 0), levels.get(global_access, 0))
            for name, val in levels.items():
                if val == min_level:
                    result[eid] = name
                    break
    return result


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Cache-Control": "no-cache",
}


def _friendly_name(entity_id):
    """Resolve entity_id to its friendly_name from cached HA state."""
    state = ha_client.get_ha_format_single(entity_id)
    if state:
        return state.get("attributes", {}).get("friendly_name", entity_id)
    return entity_id


async def _send_confirm_notification(action_id, domain, service, entity_id):
    """Send an actionable notification with Approve/Deny buttons for a confirmation action."""
    notify_service = config_mgr.confirm_notify_service
    if not notify_service or "." not in notify_service:
        return
    ndomain, nservice = notify_service.split(".", 1)
    ai = config_mgr.ai_name
    fname = _friendly_name(entity_id)
    try:
        await ha_client.call_service(ndomain, nservice, {
            "title": f"ClawBridge: {ai} Needs Approval",
            "message": f"{ai} wants to call {service} on {fname}.",
            "data": {
                "tag": f"clawbridge_{action_id}",
                "actions": [
                    {"action": f"CLAWBRIDGE_APPROVE_{action_id}", "title": "Approve"},
                    {"action": f"CLAWBRIDGE_DENY_{action_id}", "title": "Deny", "destructive": True},
                ],
            },
        })
    except Exception as e:
        logger.warning("Failed to send confirmation notification: %s", e)


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

    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})


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
        headers={"Cache-Control": "no-store"},
    )


# ──────────────────────────────────────────────
# Setup API Routes (authenticated - UI)
# ──────────────────────────────────────────────

async def api_get_entities(request):
    """Return all available entities grouped by domain."""
    domains = ha_client.get_all_entities()
    exposed = config_mgr.exposed_entities
    annotations = config_mgr.entity_annotations
    constraints = config_mgr.entity_constraints
    schedules = config_mgr.entity_schedules
    return web.json_response({
        "domains": domains,
        "exposed_entities": exposed,
        "annotations": annotations,
        "constraints": constraints,
        "entity_schedules": schedules,
        "schedules": config_mgr.schedules,
    })


async def api_save_selection(request):
    """Save the entity selection (unified exposed_entities dict)."""
    data = await request.json()
    exposed = data.get("exposed_entities")
    if exposed is not None and isinstance(exposed, dict):
        config_mgr.exposed_entities = exposed
    else:
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
        "confirm_timeout_seconds": config_mgr.confirm_timeout_seconds,
        "confirm_notify_service": config_mgr.confirm_notify_service,
        "ai_name": config_mgr.ai_name,
        "gateway_url": config_mgr.gateway_url,
        "gateway_token": config_mgr.gateway_token,
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
    if "confirm_timeout_seconds" in data:
        config_mgr.confirm_timeout_seconds = data["confirm_timeout_seconds"]
    if "confirm_notify_service" in data:
        config_mgr.confirm_notify_service = data["confirm_notify_service"]
    if "ai_name" in data:
        config_mgr.ai_name = data["ai_name"]
    if "gateway_url" in data:
        config_mgr.gateway_url = data["gateway_url"]
    if "gateway_token" in data:
        config_mgr.gateway_token = data["gateway_token"]
    return web.json_response({"status": "ok"})


async def api_get_presets(request):
    return web.json_response({"presets": config_mgr.presets})


async def api_save_preset(request):
    data = await request.json()
    name = data.get("name", "")
    entities = data.get("entities", {})
    if not name:
        return web.json_response({"error": "Preset name required"}, status=400)
    config_mgr.save_preset(name, entities)
    return web.json_response({"status": "ok"})


async def api_delete_preset(request):
    name = request.match_info.get("name", "")
    if config_mgr.delete_preset(name):
        return web.json_response({"status": "ok"})
    return web.json_response({"error": "Preset not found"}, status=404)


async def api_load_preset(request):
    name = request.match_info.get("name", "")
    entities = config_mgr.load_preset(name)
    if entities is not None:
        return web.json_response({"entities": entities})
    return web.json_response({"error": "Preset not found"}, status=404)


async def api_export_config(request):
    return web.json_response(config_mgr.export_config())


async def api_import_config(request):
    data = await request.json()
    config_mgr.import_config(data)
    return web.json_response({"status": "ok"})


async def api_get_services(request):
    services = await ha_client.get_services()
    return web.json_response({"services": services})


# ── Annotations API (authenticated) ──────────

async def api_save_annotations(request):
    """Save entity annotations."""
    data = await request.json()
    annotations = data.get("annotations", {})
    if isinstance(annotations, dict):
        config_mgr.entity_annotations = annotations
    return web.json_response({"status": "ok"})


async def api_save_annotation(request):
    """Save a single entity annotation."""
    data = await request.json()
    entity_id = data.get("entity_id", "")
    text = data.get("annotation", "")
    if entity_id:
        config_mgr.set_annotation(entity_id, text)
    return web.json_response({"status": "ok"})


# ── Constraints API (authenticated) ──────────

async def api_save_constraints(request):
    """Save entity constraints."""
    data = await request.json()
    entity_id = data.get("entity_id", "")
    constraints = data.get("constraints", {})
    if entity_id:
        config_mgr.set_constraints(entity_id, constraints)
    return web.json_response({"status": "ok"})


async def api_get_constraints(request):
    """Get all constraints."""
    return web.json_response({"constraints": config_mgr.entity_constraints})


# ── API Keys Management (authenticated) ──────

async def api_list_keys(request):
    return web.json_response({"keys": config_mgr.list_api_keys()})


async def api_create_key(request):
    data = await request.json()
    name = data.get("name", "Unnamed")
    entities = data.get("entities", {})
    rate_limit = data.get("rate_limit", 0)
    key_id, full_key = config_mgr.create_api_key(name, entities, rate_limit)
    return web.json_response({"key_id": key_id, "key": full_key, "name": name})


async def api_delete_key(request):
    key_id = request.match_info.get("key_id", "")
    if config_mgr.delete_api_key(key_id):
        return web.json_response({"status": "ok"})
    return web.json_response({"error": "Key not found"}, status=404)


# ── Schedules Management (authenticated) ─────

async def api_list_schedules(request):
    return web.json_response({
        "schedules": config_mgr.schedules,
        "entity_schedules": config_mgr.entity_schedules,
    })


async def api_create_schedule(request):
    data = await request.json()
    schedule_id = config_mgr.create_schedule(
        name=data.get("name", "Unnamed"),
        start=data.get("start", "00:00"),
        end=data.get("end", "23:59"),
        days=data.get("days", [0, 1, 2, 3, 4, 5, 6]),
    )
    return web.json_response({"schedule_id": schedule_id})


async def api_update_schedule(request):
    schedule_id = request.match_info.get("schedule_id", "")
    data = await request.json()
    if config_mgr.update_schedule(schedule_id, **data):
        return web.json_response({"status": "ok"})
    return web.json_response({"error": "Schedule not found"}, status=404)


async def api_delete_schedule(request):
    schedule_id = request.match_info.get("schedule_id", "")
    if config_mgr.delete_schedule(schedule_id):
        return web.json_response({"status": "ok"})
    return web.json_response({"error": "Schedule not found"}, status=404)


async def api_set_entity_schedule(request):
    data = await request.json()
    entity_id = data.get("entity_id", "")
    schedule_id = data.get("schedule_id")  # None to remove
    if entity_id:
        config_mgr.set_entity_schedule(entity_id, schedule_id)
    return web.json_response({"status": "ok"})


# ── Confirmation Actions (authenticated) ─────

async def api_list_pending_actions(request):
    """List pending confirmation actions."""
    active = {}
    now = time.time()
    timeout = config_mgr.confirm_timeout_seconds
    for action_id, action in _pending_actions.items():
        if action["status"] == "pending" and (now - action["timestamp"]) < timeout:
            active[action_id] = {
                "domain": action["domain"],
                "service": action["service"],
                "entity_id": action["entity_id"],
                "data": action.get("data", {}),
                "age_seconds": int(now - action["timestamp"]),
            }
    return web.json_response({"pending": active})


async def api_action_approve(request):
    """Approve a pending confirmation action."""
    action_id = request.match_info.get("action_id", "")
    action = _pending_actions.get(action_id)
    if not action or action["status"] != "pending":
        return web.json_response({"error": "Action not found or already resolved"}, status=404)

    if (time.time() - action["timestamp"]) > config_mgr.confirm_timeout_seconds:
        action["status"] = "expired"
        return web.json_response({"error": "Action expired"}, status=410)

    # Execute the service call
    ok, result = await ha_client.call_service(action["domain"], action["service"], action["data"])
    action["status"] = "approved"

    await audit_logger.log_action(
        "confirmed_service_call",
        entity_id=action["entity_id"], domain=action["domain"],
        service=action["service"], source_ip=action.get("source_ip"),
        result="success" if ok else "error",
        error=str(result.get("error", "")) if not ok else None,
    )

    if ok:
        return web.json_response({"status": "approved", "result": result})
    return web.json_response({"status": "approved", "error": result.get("error")}, status=502)


async def api_action_deny(request):
    """Deny a pending confirmation action."""
    action_id = request.match_info.get("action_id", "")
    action = _pending_actions.get(action_id)
    if not action or action["status"] != "pending":
        return web.json_response({"error": "Action not found or already resolved"}, status=404)

    action["status"] = "denied"
    await audit_logger.log_action(
        "denied_service_call",
        entity_id=action["entity_id"], domain=action["domain"],
        service=action["service"], source_ip=action.get("source_ip"),
        result="denied", error="user_denied",
    )
    return web.json_response({"status": "denied"})


# ── Audit API (authenticated) ────────────────

async def api_get_audit_logs(request):
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
    await audit_logger.clear_logs()
    return web.json_response({"status": "ok"})


# ── Stats API (authenticated) ────────────────

async def api_get_stats(request):
    """Return dashboard statistics."""
    hours = int(request.query.get("hours", 24))
    stats = await audit_logger.get_stats(hours=hours)
    # Add live info
    stats["total_exposed"] = len(config_mgr.get_all_exposed_ids())
    stats["total_read"] = len(config_mgr.get_read_entity_ids())
    stats["total_confirm"] = len(config_mgr.get_confirm_entity_ids())
    stats["total_control"] = len(config_mgr.get_control_entity_ids())
    stats["api_keys_count"] = len(config_mgr.api_keys)
    stats["schedules_count"] = len(config_mgr.schedules)
    stats["ws_connected"] = ha_client.ws_connected
    stats["ws_clients"] = len(_ws_clients)
    return web.json_response(stats)


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
        "version": "clawbridge-1.4.0",
        "location_name": "ClawBridge",
    }, headers=CORS_HEADERS)


async def ha_api_get_states(request):
    """GET /api/states - Return all exposed entities in HA state format."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    effective = _get_effective_entities(key_config)
    entity_ids = list(effective.keys())

    states = ha_client.get_ha_format_states(
        entity_ids, filter_unavailable=config_mgr.filter_unavailable
    )

    # Enrich with annotations and constraints
    annotations = config_mgr.entity_annotations
    constraints = config_mgr.entity_constraints
    for state in states:
        eid = state["entity_id"]
        ann = annotations.get(eid)
        if ann:
            state["annotation"] = ann
        con = constraints.get(eid)
        if con:
            state["constraints"] = con
        state["access_level"] = effective.get(eid, "read")

    return web.json_response(states, headers=CORS_HEADERS)


async def ha_api_get_state(request):
    """GET /api/states/{entity_id} - Return single entity if exposed, else 404."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    entity_id = request.match_info.get("entity_id", "")
    effective = _get_effective_entities(key_config)

    if entity_id not in effective:
        return web.json_response(
            {"message": f"Entity not found: {entity_id}"}, status=404, headers=CORS_HEADERS
        )

    state = ha_client.get_ha_format_single(entity_id)
    if not state:
        return web.json_response(
            {"message": f"Entity not found: {entity_id}"}, status=404, headers=CORS_HEADERS
        )

    # Enrich
    ann = config_mgr.get_annotation(entity_id)
    if ann:
        state["annotation"] = ann
    con = config_mgr.get_constraints(entity_id)
    if con:
        state["constraints"] = con
    state["access_level"] = effective.get(entity_id, "read")

    return web.json_response(state, headers=CORS_HEADERS)


async def ha_api_get_services(request):
    """GET /api/services - Return services only for domains with control/confirm entities."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    control_domains = config_mgr.get_control_domains()
    all_services = await ha_client.get_services()
    filtered = []
    for domain, services in all_services.items():
        if domain in control_domains:
            filtered.append({"domain": domain, "services": services})
    return web.json_response(filtered, headers=CORS_HEADERS)


async def ha_api_call_service(request):
    """POST /api/services/{domain}/{service} - HA-compatible service call with full validation."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    custom_rate = key_config.get("rate_limit") if key_config else None
    if not _check_rate_limit(ip, custom_rate if custom_rate else None):
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

    effective = _get_effective_entities(key_config)

    # Extract entity_id(s) from body
    raw_entity = body.get("entity_id")
    entity_ids = []
    if isinstance(raw_entity, str):
        entity_ids = [raw_entity]
    elif isinstance(raw_entity, list):
        entity_ids = [e for e in raw_entity if isinstance(e, str)]

    # Read-safe services: these only return data and don't modify state,
    # so they are allowed for entities with "read" (or higher) access.
    READ_SAFE_SERVICES = {
        ("todo", "get_items"),
    }
    is_read_safe = (domain, service) in READ_SAFE_SERVICES

    # Validate each entity against allowlist
    for eid in entity_ids:
        access = effective.get(eid, False)
        if not access:
            await audit_logger.log_action(
                "service_call", entity_id=eid, domain=domain, service=service,
                source_ip=ip, result="denied", error="entity_not_exposed",
            )
            return web.json_response(
                {"message": f"Entity not exposed: {eid}"}, status=403, headers=CORS_HEADERS
            )
        if access == "read" and not is_read_safe:
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

    # If no entity specified, inject allowed control/confirm entities for this domain
    if not entity_ids:
        control_entities_in_domain = [
            eid for eid, access in effective.items()
            if access in ("control", "confirm") and eid.startswith(domain + ".")
        ]
        if not control_entities_in_domain:
            await audit_logger.log_action(
                "service_call", domain=domain, service=service,
                source_ip=ip, result="denied", error="domain_not_exposed",
            )
            return web.json_response(
                {"message": f"No control entities exposed in domain {domain}"}, status=403, headers=CORS_HEADERS
            )
        body["entity_id"] = control_entities_in_domain if len(control_entities_in_domain) > 1 else control_entities_in_domain[0]
        entity_ids = control_entities_in_domain

    # Read-safe services skip schedule, constraint, and confirmation checks
    if is_read_safe:
        # Pass return_response as query parameter so HA returns the actual data
        ok, result = await ha_client.call_service(domain, service, body, return_response=True)
        elapsed_ms = int((time.time() - start_time) * 1000)
        if ok:
            await audit_logger.log_action(
                "service_call", entity_id=entity_ids[0] if entity_ids else None,
                domain=domain, service=service,
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

    # Check schedule restrictions
    for eid in entity_ids:
        if not config_mgr.is_within_schedule(eid):
            schedule_id = config_mgr.entity_schedules.get(eid, "")
            schedule = config_mgr.schedules.get(schedule_id, {})
            schedule_name = schedule.get("name", schedule_id)
            await audit_logger.log_action(
                "service_call", entity_id=eid, domain=domain, service=service,
                source_ip=ip, result="denied", error=f"schedule_restricted:{schedule_name}",
            )
            return web.json_response(
                {"message": f"Entity {eid} is outside its allowed time schedule ({schedule_name})"}, status=403, headers=CORS_HEADERS
            )

    # Check parameter constraints and clamp
    params_to_check = {k: v for k, v in body.items() if k != "entity_id"}
    all_violations = []
    for eid in entity_ids:
        clamped, violations = config_mgr.validate_parameters(eid, params_to_check)
        if violations:
            all_violations.extend(violations)
            # Update body with clamped values
            for k, v in clamped.items():
                body[k] = v

    if all_violations:
        await audit_logger.log_action(
            "service_call", entity_id=entity_ids[0] if entity_ids else None,
            domain=domain, service=service,
            parameters={"clamped": all_violations},
            source_ip=ip, result="clamped",
        )

    # Check if any entity requires confirmation
    confirm_entities = [eid for eid in entity_ids if effective.get(eid) == "confirm"]
    if confirm_entities:
        action_id = "act_" + secrets.token_urlsafe(12)
        _pending_actions[action_id] = {
            "domain": domain,
            "service": service,
            "entity_id": confirm_entities[0],
            "data": body,
            "timestamp": time.time(),
            "status": "pending",
            "source_ip": ip,
        }

        # Send actionable notification with Approve/Deny buttons
        await _send_confirm_notification(action_id, domain, service, confirm_entities[0])

        await audit_logger.log_action(
            "confirmation_requested",
            entity_id=confirm_entities[0], domain=domain, service=service,
            source_ip=ip, result="pending",
        )

        return web.json_response({
            "action_id": action_id,
            "status": "pending",
            "message": f"Action requires human approval. Poll GET /api/actions/{action_id} for status.",
            "timeout_seconds": config_mgr.confirm_timeout_seconds,
        }, status=202, headers=CORS_HEADERS)

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


# ── Confirmation action status (public) ──────

async def ha_api_action_status(request):
    """GET /api/actions/{action_id} - Check confirmation action status."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    action_id = request.match_info.get("action_id", "")
    action = _pending_actions.get(action_id)
    if not action:
        return web.json_response({"message": "Action not found"}, status=404, headers=CORS_HEADERS)

    # Check expiry
    if action["status"] == "pending" and (time.time() - action["timestamp"]) > config_mgr.confirm_timeout_seconds:
        action["status"] = "expired"

    return web.json_response({
        "action_id": action_id,
        "status": action["status"],
        "entity_id": action.get("entity_id"),
        "domain": action.get("domain"),
        "service": action.get("service"),
    }, headers=CORS_HEADERS)


# ── Constraints endpoint (public) ────────────

async def ha_api_get_constraints(request):
    """GET /api/constraints - Return all parameter constraints for exposed entities."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    effective = _get_effective_entities(key_config)
    all_constraints = config_mgr.entity_constraints
    # Only return constraints for entities this key can see
    filtered = {eid: con for eid, con in all_constraints.items() if eid in effective}
    return web.json_response(filtered, headers=CORS_HEADERS)


# ── History endpoint (public) ────────────────

async def ha_api_history(request):
    """GET /api/history/period/{timestamp} - Proxy HA history for exposed entities only."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    # Stricter rate limit for history queries
    if not _check_rate_limit(ip + "_history", 10):
        return web.json_response(
            {"message": "History rate limit exceeded (10/min)"}, status=429, headers=CORS_HEADERS
        )

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    effective = _get_effective_entities(key_config)
    timestamp = request.match_info.get("timestamp", "")
    end_time = request.query.get("end_time")

    # Filter requested entities to only exposed ones
    requested = request.query.get("filter_entity_id", "")
    if requested:
        requested_ids = [e.strip() for e in requested.split(",")]
        entity_ids = [eid for eid in requested_ids if eid in effective]
    else:
        entity_ids = list(effective.keys())

    if not entity_ids:
        return web.json_response([], headers=CORS_HEADERS)

    # Cap to 20 entities per history query for performance
    entity_ids = entity_ids[:20]

    history = await ha_client.get_history(timestamp, entity_ids, end_time)
    return web.json_response(history, headers=CORS_HEADERS)


# ── Context endpoint (public) ────────────────

async def ha_api_context(request):
    """GET /api/context - Give AI a complete summary of its permissions and capabilities."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    effective = _get_effective_entities(key_config)

    # Bucket entities by access level
    read_entities = sorted(eid for eid, lvl in effective.items() if lvl == "read")
    confirm_entities = sorted(eid for eid, lvl in effective.items() if lvl == "confirm")
    control_entities = sorted(eid for eid, lvl in effective.items() if lvl == "control")

    total = len(effective)
    summary = (
        f"You have access to {total} entities: "
        f"{len(read_entities)} read-only, "
        f"{len(confirm_entities)} require confirmation, "
        f"{len(control_entities)} controllable."
    )

    # Annotations for exposed entities only
    all_annotations = config_mgr.entity_annotations
    annotations = {eid: ann for eid, ann in all_annotations.items() if eid in effective and ann}

    # Constraints for exposed entities only
    all_constraints = config_mgr.entity_constraints
    constraints = {eid: con for eid, con in all_constraints.items() if eid in effective and con}

    # Schedules for exposed entities only
    all_entity_schedules = config_mgr.entity_schedules
    all_schedules = config_mgr.schedules
    schedules = {}
    for eid, sched_id in all_entity_schedules.items():
        if eid in effective and sched_id in all_schedules:
            schedules[eid] = all_schedules[sched_id]

    # Available services: unique domain.service for domains with control/confirm entities
    actionable_domains = set()
    for eid, lvl in effective.items():
        if lvl in ("control", "confirm") and "." in eid:
            actionable_domains.add(eid.split(".")[0])

    available_services = []
    if actionable_domains:
        try:
            ok, all_services = await ha_client.get_services()
            if ok and isinstance(all_services, dict):
                for domain, services in all_services.items():
                    if domain in actionable_domains and isinstance(services, dict):
                        for svc_name in sorted(services.keys()):
                            available_services.append(f"{domain}.{svc_name}")
        except Exception:
            pass

    limitations = [
        "Entities listed under 'read' can only be observed. Service calls will be rejected.",
        "Entities listed under 'confirm' require human approval. Service calls return 202 and are queued.",
        "Parameter constraints are enforced server-side. Values outside min/max are auto-clamped.",
        "Entities with time schedules can only be controlled during the listed hours and days.",
        "Rate limiting is active. Exceeding the limit returns 429.",
    ]

    return web.json_response({
        "summary": summary,
        "entities": {
            "read": read_entities,
            "confirm": confirm_entities,
            "control": control_entities,
        },
        "annotations": annotations,
        "constraints": constraints,
        "schedules": schedules,
        "available_services": available_services,
        "limitations": limitations,
    }, headers=CORS_HEADERS)


# ── WebSocket endpoint (public) ──────────────

async def ha_api_websocket(request):
    """GET /api/websocket - WebSocket for real-time state change streaming."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403)

    # Limit concurrent WebSocket connections to prevent resource exhaustion
    if len(_ws_clients) >= 50:
        return web.json_response({"message": "Too many WebSocket connections"}, status=503)

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    # Auth handshake
    await ws.send_json({"type": "auth_required"})

    key_config = None
    has_api_keys = bool(config_mgr.api_keys)

    try:
        msg = await asyncio.wait_for(ws.receive_json(), timeout=10)
    except (asyncio.TimeoutError, Exception):
        await ws.close(message=b"Auth timeout")
        return ws

    if has_api_keys:
        token = msg.get("api_key") or msg.get("access_token", "")
        key_id, key_config = config_mgr.get_key_by_token(token)
        if not key_id:
            await ws.send_json({"type": "auth_invalid", "message": "Invalid API key"})
            await ws.close()
            return ws
    # No keys configured = open access

    await ws.send_json({"type": "auth_ok"})

    effective = _get_effective_entities(key_config)
    subscribed_ids = set(effective.keys())  # Default: all exposed entities

    # Register client
    client_entry = (ws, subscribed_ids)
    _ws_clients.append(client_entry)

    try:
        async for raw_msg in ws:
            if raw_msg.type == aiohttp_client.WSMsgType.TEXT:
                try:
                    data = json.loads(raw_msg.data)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type == "subscribe":
                    # Client can narrow their subscription
                    requested = data.get("entity_ids", [])
                    if requested:
                        subscribed_ids.clear()
                        subscribed_ids.update(eid for eid in requested if eid in effective)
                    await ws.send_json({"type": "subscription_ok", "count": len(subscribed_ids)})

            elif raw_msg.type in (aiohttp_client.WSMsgType.CLOSED, aiohttp_client.WSMsgType.ERROR):
                break
    finally:
        try:
            _ws_clients.remove(client_entry)
        except ValueError:
            pass

    return ws


async def _broadcast_state_change(entity_id, new_state, old_state):
    """Broadcast state changes to all connected WebSocket clients."""
    if not _ws_clients:
        return

    message = json.dumps({
        "type": "state_changed",
        "entity_id": entity_id,
        "new_state": new_state,
        "old_state": old_state,
    })

    dead_clients = []
    for client in _ws_clients:
        ws, subscribed_ids = client
        if entity_id in subscribed_ids:
            try:
                await ws.send_str(message)
            except Exception:
                dead_clients.append(client)

    for client in dead_clients:
        try:
            _ws_clients.remove(client)
        except ValueError:
            pass


# ──────────────────────────────────────────────
# Legacy AI Endpoints (backward compatibility)
# ──────────────────────────────────────────────

async def api_ai_sensors(request):
    """GET /api/ai-sensors - Legacy endpoint: sensor data + allowed actions."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"message": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"message": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    effective = _get_effective_entities(key_config)
    all_exposed = list(effective.keys())

    data = await ha_client.get_exposed_data(
        all_exposed,
        filter_unavailable=config_mgr.filter_unavailable,
        compact=config_mgr.compact_mode,
    )
    data["entity_access"] = effective
    data["controllable_entities"] = [eid for eid, access in effective.items() if access == "control"]
    data["control_domains"] = list(config_mgr.get_control_domains())

    # Include annotations
    annotations = config_mgr.entity_annotations
    data["annotations"] = {eid: ann for eid, ann in annotations.items() if eid in effective}

    return web.json_response(data, headers=CORS_HEADERS)


async def api_ai_action(request):
    """POST /api/ai-action - Legacy endpoint for AI to call an allowed service."""
    ip = _get_client_ip(request)
    if not _check_ip_allowlist(ip):
        return web.json_response({"error": "IP not allowed"}, status=403, headers=CORS_HEADERS)

    if not _check_rate_limit(ip):
        return web.json_response({"error": "Rate limit exceeded"}, status=429, headers=CORS_HEADERS)

    key_id, key_config = _check_api_key(request)
    if key_id is None:
        return web.json_response({"error": "Invalid API key"}, status=401, headers=CORS_HEADERS)

    effective = _get_effective_entities(key_config)

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

    # Validate entity access level (using per-key effective entities)
    if entity_id:
        access = effective.get(entity_id, False)
        if not access:
            await audit_logger.log_action(
                "service_call", entity_id=entity_id, domain=domain, service=service,
                source_ip=ip, result="denied", error="entity_not_exposed",
            )
            return web.json_response({"error": f"Entity {entity_id} is not exposed"}, status=403)
        if access == "read":
            await audit_logger.log_action(
                "service_call", entity_id=entity_id, domain=domain, service=service,
                source_ip=ip, result="denied", error="read_only_entity",
            )
            return web.json_response({"error": f"Entity {entity_id} is read-only"}, status=403)

        # Check schedule
        if not config_mgr.is_within_schedule(entity_id):
            await audit_logger.log_action(
                "service_call", entity_id=entity_id, domain=domain, service=service,
                source_ip=ip, result="denied", error="schedule_restricted",
            )
            return web.json_response({"error": f"Entity {entity_id} is outside its allowed time schedule"}, status=403)

        # Check if confirmation required
        if access == "confirm":
            action_id = "act_" + secrets.token_urlsafe(12)
            service_data = dict(extra_data)
            service_data["entity_id"] = entity_id
            _pending_actions[action_id] = {
                "domain": domain, "service": service, "entity_id": entity_id,
                "data": service_data, "timestamp": time.time(),
                "status": "pending", "source_ip": ip,
            }
            # Send actionable notification with Approve/Deny buttons
            await _send_confirm_notification(action_id, domain, service, entity_id)
            return web.json_response({
                "action_id": action_id, "status": "pending",
                "message": f"Requires human approval. Poll GET /api/actions/{action_id}",
            }, status=202, headers=CORS_HEADERS)
    else:
        # No entity_id: inject allowed control entities (scoped to API key)
        control_entities_in_domain = [
            eid for eid, acc in effective.items()
            if acc in ("control", "confirm") and eid.startswith(domain + ".")
        ]
        if not control_entities_in_domain:
            await audit_logger.log_action(
                "service_call", domain=domain, service=service,
                source_ip=ip, result="denied", error="domain_not_exposed",
            )
            return web.json_response({"error": f"No control entities in domain {domain}"}, status=403)
        entity_id = control_entities_in_domain[0] if len(control_entities_in_domain) == 1 else None
        extra_data["entity_id"] = control_entities_in_domain if len(control_entities_in_domain) > 1 else control_entities_in_domain[0]

    service_data = dict(extra_data)
    if entity_id:
        service_data["entity_id"] = entity_id

    # Validate constraints for the target entity
    constraint_target = entity_id or (extra_data.get("entity_id") if isinstance(extra_data.get("entity_id"), str) else "")
    if constraint_target:
        clamped, violations = config_mgr.validate_parameters(constraint_target, service_data)
        if violations:
            service_data.update(clamped)

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


async def _cleanup_stale_data():
    """Periodically clean up expired pending actions and stale rate buckets."""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        now = time.time()
        timeout = config_mgr.confirm_timeout_seconds

        # Clean expired/resolved pending actions (keep for 10 min after resolution for polling)
        stale_actions = [
            aid for aid, a in _pending_actions.items()
            if (a["status"] != "pending" and (now - a["timestamp"]) > 600) or
               (a["status"] == "pending" and (now - a["timestamp"]) > timeout + 60)
        ]
        for aid in stale_actions:
            del _pending_actions[aid]
        if stale_actions:
            logger.debug("Cleaned %d stale pending actions", len(stale_actions))

        # Clean stale rate buckets (no activity for 5+ minutes)
        stale_ips = [ip for ip, b in _rate_buckets.items() if (now - b["last_refill"]) > 300]
        for ip in stale_ips:
            del _rate_buckets[ip]
        if stale_ips:
            logger.debug("Cleaned %d stale rate buckets", len(stale_ips))


# ──────────────────────────────────────────────
# Notification Action Handler
# ──────────────────────────────────────────────

async def _handle_notification_action(action_str, event_data):
    """Handle Approve/Deny button taps from mobile notifications."""
    if action_str.startswith("CLAWBRIDGE_APPROVE_"):
        action_id = action_str[len("CLAWBRIDGE_APPROVE_"):]
        action = _pending_actions.get(action_id)
        if not action or action["status"] != "pending":
            logger.debug("Notification approve for unknown/resolved action: %s", action_id)
            return

        if (time.time() - action["timestamp"]) > config_mgr.confirm_timeout_seconds:
            action["status"] = "expired"
            logger.info("Notification approve for expired action: %s", action_id)
            return

        # Execute the service call
        ok, result = await ha_client.call_service(action["domain"], action["service"], action["data"])
        action["status"] = "approved"

        await audit_logger.log_action(
            "confirmed_service_call",
            entity_id=action["entity_id"], domain=action["domain"],
            service=action["service"], source_ip=action.get("source_ip"),
            result="success" if ok else "error",
            error=str(result.get("error", "")) if not ok else None,
        )
        logger.info("Action %s approved via notification (entity: %s)", action_id, action["entity_id"])

    elif action_str.startswith("CLAWBRIDGE_DENY_"):
        action_id = action_str[len("CLAWBRIDGE_DENY_"):]
        action = _pending_actions.get(action_id)
        if not action or action["status"] != "pending":
            logger.debug("Notification deny for unknown/resolved action: %s", action_id)
            return

        action["status"] = "denied"
        await audit_logger.log_action(
            "denied_service_call",
            entity_id=action["entity_id"], domain=action["domain"],
            service=action["service"], source_ip=action.get("source_ip"),
            result="denied",
        )
        logger.info("Action %s denied via notification (entity: %s)", action_id, action["entity_id"])


# ──────────────────────────────────────────────
# Chat / AI Gateway Proxy
# ──────────────────────────────────────────────

async def api_chat(request):
    """Streaming SSE proxy to OpenClaw Gateway /v1/chat/completions."""
    gateway_url = config_mgr.gateway_url
    gateway_token = config_mgr.gateway_token
    if not gateway_url:
        return web.json_response({"error": "Gateway URL not configured"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    user_message = data.get("message", "").strip()
    history = data.get("history", [])
    if not user_message:
        return web.json_response({"error": "Empty message"}, status=400)

    # Build OpenAI-format messages (last 6 turns + new)
    messages = []
    for msg in history[-12:]:  # last 6 turns (user+assistant each)
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant", "system") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    # Prepare gateway request
    url = gateway_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if gateway_token:
        headers["Authorization"] = f"Bearer {gateway_token}"

    payload = {
        "messages": messages,
        "stream": True,
    }

    # Start SSE response
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    try:
        timeout = aiohttp_client.ClientTimeout(total=120)
        async with aiohttp_client.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as upstream:
                if upstream.status != 200:
                    error_text = await upstream.text()
                    await response.write(f"data: {json.dumps({'error': error_text})}\n\n".encode())
                    await response.write(b"data: [DONE]\n\n")
                    return response

                async for line in upstream.content:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if not decoded:
                        continue
                    if decoded.startswith("data: "):
                        chunk_data = decoded[6:]
                        if chunk_data == "[DONE]":
                            await response.write(b"data: [DONE]\n\n")
                            break
                        try:
                            chunk = json.loads(chunk_data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                await response.write(f"data: {json.dumps({'content': content})}\n\n".encode())
                        except (json.JSONDecodeError, IndexError, KeyError):
                            pass
    except asyncio.TimeoutError:
        await response.write(f"data: {json.dumps({'error': 'Gateway timeout'})}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")
    except Exception as e:
        logger.error("Chat proxy error: %s", e)
        await response.write(f"data: {json.dumps({'error': str(e)})}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")

    return response


async def api_chat_history_get(request):
    """Return stored chat history."""
    return web.json_response({"history": config_mgr.chat_history})


async def api_chat_history_save(request):
    """Save chat history (capped at 200)."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    history = data.get("history", [])
    if not isinstance(history, list):
        return web.json_response({"error": "history must be an array"}, status=400)
    config_mgr.chat_history = history
    return web.json_response({"status": "ok", "count": len(config_mgr.chat_history)})


async def api_chat_history_clear(request):
    """Clear chat history."""
    config_mgr.chat_history = []
    return web.json_response({"status": "ok"})


async def api_chat_status(request):
    """Return whether gateway is configured."""
    return web.json_response({
        "configured": bool(config_mgr.gateway_url),
        "has_token": bool(config_mgr.gateway_token),
    })


# ──────────────────────────────────────────────
# App Setup
# ──────────────────────────────────────────────

async def on_startup(app):
    """Start HA client and background tasks on app startup."""
    await fetch_ingress_url()
    await ha_client.start()

    # Register state change broadcaster for WebSocket clients
    ha_client.subscribe_state_changes(_broadcast_state_change)

    # Register notification action handler for Approve/Deny button taps
    ha_client.subscribe_notification_actions(_handle_notification_action)

    app["refresh_task"] = asyncio.create_task(
        ha_client.periodic_refresh(config_mgr.refresh_interval)
    )
    if config_mgr.audit_enabled:
        app["audit_cleanup_task"] = asyncio.create_task(
            audit_logger.periodic_cleanup(config_mgr.audit_retention_days)
        )
    app["stale_cleanup_task"] = asyncio.create_task(_cleanup_stale_data())
    logger.info("ClawBridge started")


async def on_cleanup(app):
    """Clean up on shutdown."""
    for task_name in ("refresh_task", "audit_cleanup_task", "stale_cleanup_task"):
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

    # Annotations & Constraints
    app.router.add_post("/api/annotations", api_save_annotations)
    app.router.add_post("/api/annotation", api_save_annotation)
    app.router.add_post("/api/constraints", api_save_constraints)
    app.router.add_get("/api/constraints", api_get_constraints)

    # API Keys
    app.router.add_get("/api/keys", api_list_keys)
    app.router.add_post("/api/keys", api_create_key)
    app.router.add_delete("/api/keys/{key_id}", api_delete_key)

    # Schedules
    app.router.add_get("/api/schedules", api_list_schedules)
    app.router.add_post("/api/schedules", api_create_schedule)
    app.router.add_post("/api/schedules/{schedule_id}", api_update_schedule)
    app.router.add_delete("/api/schedules/{schedule_id}", api_delete_schedule)
    app.router.add_post("/api/entity-schedule", api_set_entity_schedule)

    # Confirmation
    app.router.add_get("/api/pending-actions", api_list_pending_actions)
    app.router.add_post("/api/actions/{action_id}/approve", api_action_approve)
    app.router.add_post("/api/actions/{action_id}/deny", api_action_deny)

    # Audit & Stats
    app.router.add_get("/api/audit/logs", api_get_audit_logs)
    app.router.add_delete("/api/audit/logs", api_clear_audit_logs)
    app.router.add_get("/api/stats", api_get_stats)

    # Chat / AI Gateway
    app.router.add_post("/api/chat", api_chat)
    app.router.add_get("/api/chat/history", api_chat_history_get)
    app.router.add_post("/api/chat/history", api_chat_history_save)
    app.router.add_delete("/api/chat/history", api_chat_history_clear)
    app.router.add_get("/api/chat/status", api_chat_status)

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

    # Extended endpoints
    app.router.add_get("/api/context", ha_api_context)
    app.router.add_get("/api/constraints", ha_api_get_constraints)
    app.router.add_get("/api/history/period/{timestamp}", ha_api_history)
    app.router.add_get("/api/actions/{action_id}", ha_api_action_status)

    # WebSocket
    app.router.add_get("/api/websocket", ha_api_websocket)

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
