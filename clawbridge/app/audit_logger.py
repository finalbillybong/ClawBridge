"""Audit logger for ClawBridge.

Logs all AI-initiated service calls to a JSONL file.
Thread-safe (asyncio lock). Supports retention policies.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

AUDIT_DIR = "/data"
AUDIT_FILE = os.path.join(AUDIT_DIR, "audit.jsonl")
MAX_RETURN_ENTRIES = 500


class AuditLogger:
    """Append-only JSONL audit logger for AI-initiated actions."""

    def __init__(self):
        self._lock = asyncio.Lock()

    async def log_action(self, event_type, entity_id=None, domain=None, service=None,
                         parameters=None, source_ip=None, result="success", error=None,
                         response_time_ms=None):
        """Log a single audit event."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "entity_id": entity_id,
            "domain": domain,
            "service": service,
            "parameters": parameters,
            "source_ip": source_ip,
            "result": result,
            "error": error,
            "response_time_ms": response_time_ms,
        }
        # Remove None values for compactness
        entry = {k: v for k, v in entry.items() if v is not None}

        async with self._lock:
            try:
                os.makedirs(AUDIT_DIR, exist_ok=True)
                with open(AUDIT_FILE, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                logger.error("Failed to write audit log: %s", e)

    async def get_logs(self, limit=200, entity_filter=None, result_filter=None,
                       since=None, until=None):
        """Read audit log entries with optional filters. Returns newest first."""
        entries = []
        if not os.path.exists(AUDIT_FILE):
            return entries

        async with self._lock:
            try:
                with open(AUDIT_FILE, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # Apply filters
                        if entity_filter and entry.get("entity_id") != entity_filter:
                            continue
                        if result_filter and entry.get("result") != result_filter:
                            continue
                        if since:
                            ts = entry.get("timestamp", "")
                            if ts < since:
                                continue
                        if until:
                            ts = entry.get("timestamp", "")
                            if ts > until:
                                continue

                        entries.append(entry)
            except Exception as e:
                logger.error("Failed to read audit log: %s", e)

        # Newest first, capped
        entries.reverse()
        return entries[:min(limit, MAX_RETURN_ENTRIES)]

    async def cleanup_old_logs(self, retention_days=30):
        """Remove audit entries older than retention_days."""
        if not os.path.exists(AUDIT_FILE):
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        kept = []
        removed = 0

        async with self._lock:
            try:
                with open(AUDIT_FILE, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if entry.get("timestamp", "") >= cutoff:
                            kept.append(line)
                        else:
                            removed += 1

                with open(AUDIT_FILE, "w") as f:
                    for line in kept:
                        f.write(line + "\n")

                if removed > 0:
                    logger.info("Audit cleanup: removed %d old entries, kept %d", removed, len(kept))
            except Exception as e:
                logger.error("Failed to clean up audit log: %s", e)

        return removed

    async def clear_logs(self):
        """Clear all audit logs."""
        async with self._lock:
            try:
                if os.path.exists(AUDIT_FILE):
                    os.remove(AUDIT_FILE)
                    logger.info("Audit log cleared")
            except Exception as e:
                logger.error("Failed to clear audit log: %s", e)

    async def periodic_cleanup(self, retention_days=30):
        """Background task to clean up old audit entries daily."""
        while True:
            await asyncio.sleep(86400)  # 24 hours
            await self.cleanup_old_logs(retention_days)
