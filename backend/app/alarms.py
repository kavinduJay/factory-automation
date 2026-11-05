"""Alarm lifecycle: active -> acked -> cleared. One open alarm per entity and type."""
import asyncpg

from .db import record

ALARM_COLS = ("id, entity_id, device_id, type, severity, status, message, started_at, "
              "acked_by, acked_at, cleared_at, rule_id, details")


class AlarmService:
    def __init__(self, pool: asyncpg.Pool, hub) -> None:
        self.pool = pool
        self.hub = hub

    async def raise_(self, *, entity_id: str, type: str, severity: str, message: str = "",
                     device_id: str | None = None, rule_id: int | None = None,
                     details: dict | None = None, ts=None, conn=None) -> dict | None:
        """Open an alarm. Returns it if new, None if one was already open."""
        sql = f"""
            INSERT INTO alarm (entity_id, device_id, type, severity, message, rule_id, details, started_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, coalesce($8, now()))
            ON CONFLICT (entity_id, type) WHERE cleared_at IS NULL DO NOTHING
            RETURNING {ALARM_COLS}"""
        args = (entity_id, device_id, type, severity, message, rule_id, details or {}, ts)
        if conn is not None:
            row = await conn.fetchrow(sql, *args)
        else:
            row = await self.pool.fetchrow(sql, *args)
        alarm = record(row)
        if alarm:
            await self.hub.broadcast({"type": "alarm", "alarm": alarm})
        return alarm

    async def clear(self, *, entity_id: str, type: str, ts=None, conn=None) -> dict | None:
        sql = f"""
            UPDATE alarm SET cleared_at = coalesce($3, now()), status = 'cleared'
            WHERE entity_id = $1 AND type = $2 AND cleared_at IS NULL
            RETURNING {ALARM_COLS}"""
        if conn is not None:
            row = await conn.fetchrow(sql, entity_id, type, ts)
        else:
            row = await self.pool.fetchrow(sql, entity_id, type, ts)
        alarm = record(row)
        if alarm:
            await self.hub.broadcast({"type": "alarm", "alarm": alarm})
        return alarm

    async def ack(self, alarm_id: int, username: str) -> dict | None:
        row = await self.pool.fetchrow(f"""
            UPDATE alarm SET acked_by = $2, acked_at = now(),
                   status = CASE WHEN cleared_at IS NULL THEN 'acked' ELSE status END
            WHERE id = $1 AND acked_at IS NULL
            RETURNING {ALARM_COLS}""", alarm_id, username)
        alarm = record(row)
        if alarm:
            await self.hub.broadcast({"type": "alarm", "alarm": alarm})
        return alarm

    async def open_alarms(self) -> list[dict]:
        rows = await self.pool.fetch(
            f"SELECT {ALARM_COLS} FROM alarm WHERE cleared_at IS NULL ORDER BY started_at DESC")
        return [dict(r) for r in rows]
