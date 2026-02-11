"""Audit logger for ClawBridge.

Logs all AI-initiated service calls to a JSONL file.
Thread-safe (asyncio lock). Supports retention policies and stats aggregation.
"""

import asyncio
import json
import logging
import os
from collections import Counter
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

        entries.reverse()
        return entries[:min(limit, MAX_RETURN_ENTRIES)]

    async def get_stats(self, hours=24):
        """Aggregate audit log statistics for the dashboard.
        Returns dict with counts, top entities, hourly breakdown, etc.
        """
        if not os.path.exists(AUDIT_FILE):
            return self._empty_stats()

        now = datetime.now(timezone.utc)
        cutoff_24h = (now - timedelta(hours=hours)).isoformat()
        cutoff_7d = (now - timedelta(days=7)).isoformat()

        total_all = 0
        total_24h = 0
        total_7d = 0
        results_all = Counter()
        results_24h = Counter()
        entity_calls = Counter()
        entity_denied = Counter()
        hourly = Counter()  # hour_offset -> count
        ip_calls = Counter()
        response_times = []

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

                        ts = entry.get("timestamp", "")
                        result = entry.get("result", "unknown")
                        eid = entry.get("entity_id", "unknown")
                        ip = entry.get("source_ip", "unknown")
                        rt = entry.get("response_time_ms")

                        total_all += 1
                        results_all[result] += 1

                        if ts >= cutoff_7d:
                            total_7d += 1

                        if ts >= cutoff_24h:
                            total_24h += 1
                            results_24h[result] += 1
                            entity_calls[eid] += 1
                            ip_calls[ip] += 1
                            if result == "denied":
                                entity_denied[eid] += 1
                            if rt is not None:
                                response_times.append(rt)

                            # Hourly breakdown
                            try:
                                entry_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                hour_ago = int((now - entry_time).total_seconds() / 3600)
                                if 0 <= hour_ago < hours:
                                    hourly[hour_ago] += 1
                            except (ValueError, TypeError):
                                pass

            except Exception as e:
                logger.error("Failed to compute audit stats: %s", e)

        # Build hourly array (0 = most recent hour)
        hourly_array = [hourly.get(i, 0) for i in range(hours)]

        avg_response = int(sum(response_times) / len(response_times)) if response_times else 0

        return {
            "total_all_time": total_all,
            "total_24h": total_24h,
            "total_7d": total_7d,
            "results_24h": dict(results_24h),
            "results_all": dict(results_all),
            "top_entities": entity_calls.most_common(10),
            "top_denied": entity_denied.most_common(10),
            "hourly": hourly_array,
            "top_ips": ip_calls.most_common(5),
            "avg_response_ms": avg_response,
            "success_rate_24h": round(
                results_24h.get("success", 0) / total_24h * 100, 1
            ) if total_24h > 0 else 0,
        }

    def _empty_stats(self):
        return {
            "total_all_time": 0, "total_24h": 0, "total_7d": 0,
            "results_24h": {}, "results_all": {},
            "top_entities": [], "top_denied": [],
            "hourly": [0] * 24, "top_ips": [],
            "avg_response_ms": 0, "success_rate_24h": 0,
        }

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
            await asyncio.sleep(86400)
            await self.cleanup_old_logs(retention_days)
