"""MQTT -> database.

Per message: parse topic, check the device is registered, de-duplicate by
msg_id, validate against the device profile, write, then notify listeners
(rule engine, WebSocket). Anything rejected goes to ingest_reject.
"""
import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import asyncpg

from ..alarms import AlarmService
from ..hub import Hub
from ..registry import Registry
from . import validate as v
from .business import record_event

log = logging.getLogger(__name__)

ReadingsListener = Callable[[str, datetime, list[v.Reading]], Awaitable[None]]


def now() -> datetime:
    return datetime.now(timezone.utc)


class Ingest:
    def __init__(self, pool: asyncpg.Pool, registry: Registry, alarms: AlarmService,
                 hub: Hub, prefix: str) -> None:
        self.pool = pool
        self.registry = registry
        self.alarms = alarms
        self.hub = hub
        self.prefix = prefix
        self.stats: Counter = Counter()
        self.readings_listeners: list[ReadingsListener] = []

    # -- entry point ------------------------------------------------------

    async def handle(self, topic: str, raw: bytes, retain: bool = False) -> str:
        """Process one message. Returns an outcome string (used by tests)."""
        self.stats["received"] += 1
        try:
            device_id, kind = v.parse_topic(topic, self.prefix)
        except v.Invalid as e:
            return await self._reject(None, topic, str(e), raw)
        if device_id not in self.registry.devices:
            return await self._reject(device_id, topic, f"unknown device {device_id}", raw)
        if kind == "status":
            return await self._status(device_id, raw, retain)
        if kind == "rpc/res":
            return "ignored"  # Phase 2
        try:
            payload = json.loads(raw)
            msg_id, ts = v.envelope(payload)
        except (ValueError, v.Invalid) as e:
            return await self._reject(device_id, topic, str(e), raw)

        handler = {"telemetry": self._telemetry, "event": self._event,
                   "attributes": self._attributes}[kind]
        outcome = await handler(device_id, topic, kind, msg_id, ts, payload)
        if outcome != "duplicate":
            await self.mark_seen(device_id)
        return outcome

    # -- kinds --------------------------------------------------------------

    async def _telemetry(self, device_id, topic, kind, msg_id, ts, payload) -> str:
        profile = self.registry.profile_of(device_id)
        try:
            ok, bad = v.readings(payload, device_id, profile, self.registry.sensors)
        except v.Invalid as e:
            return await self._reject(device_id, topic, str(e), payload)
        async with self.pool.acquire() as c, c.transaction():
            if not await self._first_time(c, msg_id, device_id, kind, ts):
                return "duplicate"
            if ok:
                await c.executemany(
                    "INSERT INTO telemetry (ts, sensor_id, key, value) VALUES ($1, $2, $3, $4) "
                    "ON CONFLICT DO NOTHING",
                    [(ts, r.sensor_id, r.key, r.value) for r in ok])
                await c.executemany(
                    """INSERT INTO telemetry_latest (sensor_id, key, ts, value) VALUES ($1, $2, $3, $4)
                       ON CONFLICT (sensor_id, key) DO UPDATE SET ts = EXCLUDED.ts, value = EXCLUDED.value
                       WHERE telemetry_latest.ts <= EXCLUDED.ts""",
                    [(r.sensor_id, r.key, ts, r.value) for r in ok])
            for reason, item in bad:
                await c.execute(
                    "INSERT INTO ingest_reject (device_id, topic, reason, payload) VALUES ($1, $2, $3, $4)",
                    device_id, topic, reason, item)
        self.stats["readings"] += len(ok)
        self.stats["rejected_readings"] += len(bad)
        if ok:
            await self.hub.broadcast({
                "type": "telemetry", "device_id": device_id, "ts": ts,
                "readings": [{"sensor": r.sensor_id, "key": r.key, "value": r.value} for r in ok]})
            for listener in self.readings_listeners:
                try:
                    await listener(device_id, ts, ok)
                except Exception:
                    log.exception("readings listener failed")
        return "ok" if not bad else "partial"

    async def _event(self, device_id, topic, kind, msg_id, ts, payload) -> str:
        device = self.registry.devices[device_id]
        profile = self.registry.profile_of(device_id)
        try:
            ev = v.event(payload, profile, device)
        except v.Invalid as e:
            # A malformed retransmit must not hide a later good copy, so the
            # msg_id is not recorded for rejects.
            return await self._reject(device_id, topic, str(e), payload)
        async with self.pool.acquire() as c, c.transaction():
            if not await self._first_time(c, msg_id, device_id, kind, ts):
                return "duplicate"
            await c.execute(
                "INSERT INTO event_log (msg_id, device_id, ts, type, payload) VALUES ($1, $2, $3, $4, $5)",
                msg_id, device_id, ts, ev["type"], payload)
            result = await record_event(c, self.alarms, device, msg_id, ts, ev)
        self.stats["events"] += 1
        await self.hub.broadcast({"type": "event", "device_id": device_id, "ts": ts,
                                  "event": ev, "result": result})
        return "ok"

    async def _attributes(self, device_id, topic, kind, msg_id, ts, payload) -> str:
        values = {k: val for k, val in payload.items() if k not in ("msg_id", "ts")}
        async with self.pool.acquire() as c, c.transaction():
            if not await self._first_time(c, msg_id, device_id, kind, ts):
                return "duplicate"
            await c.executemany(
                """INSERT INTO attribute (entity_id, scope, key, value, updated_at)
                   VALUES ($1, 'client', $2, $3, $4)
                   ON CONFLICT (entity_id, scope, key) DO UPDATE
                   SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at""",
                [(device_id, k, val, now()) for k, val in values.items()])
        await self.hub.broadcast({"type": "attributes", "device_id": device_id,
                                  "scope": "client", "values": values, "ts": ts})
        return "ok"

    async def _status(self, device_id: str, raw: bytes, retain: bool) -> str:
        text = raw.decode("utf-8", "replace").strip()
        if text.startswith("{"):
            try:
                text = str(json.loads(text).get("status", ""))
            except ValueError:
                pass
        if text not in ("online", "offline"):
            return await self._reject(device_id, f"{self.prefix}/{device_id}/status",
                                      f"bad status {text!r}", raw)
        if text == "online" and not retain:
            await self.mark_seen(device_id)
        elif text == "offline":
            await self.set_online(device_id, False, "last will" if not retain else "retained status")
        return "ok"

    # -- helpers --------------------------------------------------------------

    async def _first_time(self, c, msg_id, device_id, kind, ts) -> bool:
        row = await c.fetchrow(
            "INSERT INTO ingest_msg (msg_id, device_id, topic_kind, ts) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT DO NOTHING RETURNING msg_id", msg_id, device_id, kind, ts)
        if row is None:
            self.stats["duplicates"] += 1
            return False
        return True

    async def _reject(self, device_id, topic, reason, payload) -> str:
        self.stats["rejected"] += 1
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {"raw": payload.decode("utf-8", "replace")[:2000]}
        if not isinstance(payload, (dict, list)):
            payload = {"raw": payload}
        log.info("reject %s: %s", topic, reason)
        await self.pool.execute(
            "INSERT INTO ingest_reject (device_id, topic, reason, payload) VALUES ($1, $2, $3, $4)",
            device_id, topic, reason, payload)
        return "rejected"

    async def mark_seen(self, device_id: str) -> None:
        t = now()
        dev = self.registry.devices[device_id]
        dev["last_seen"] = t
        await self.pool.execute("UPDATE device SET last_seen = $2 WHERE id = $1", device_id, t)
        if not dev.get("online"):
            await self.set_online(device_id, True, "message received")

    async def set_online(self, device_id: str, online: bool, reason: str) -> None:
        dev = self.registry.devices[device_id]
        row = await self.pool.fetchrow(
            """UPDATE device SET online = $2, status_changed_at = now()
               WHERE id = $1 AND online IS DISTINCT FROM $2 RETURNING last_seen""",
            device_id, online)
        dev["online"] = online
        if row is None:
            return
        await self.hub.broadcast({"type": "device", "device_id": device_id, "online": online,
                                  "last_seen": row["last_seen"], "reason": reason})
        if online:
            await self.alarms.clear(entity_id=device_id, type="offline")
        else:
            await self.alarms.raise_(entity_id=device_id, device_id=device_id, type="offline",
                                     severity="major", message=f"{dev['name']} offline ({reason})")

    async def prune(self, keep_days: int = 30) -> int:
        """Forget msg_ids older than keep_days (devices buffer at most 7)."""
        result = await self.pool.execute(
            "DELETE FROM ingest_msg WHERE received_at < $1", now() - timedelta(days=keep_days))
        return int(result.split()[-1])
