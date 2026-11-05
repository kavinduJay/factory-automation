"""Assets, profiles, devices, live state, history, settings, ingest status."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..db import records
from ..engine.settings import SettingsError
from .auth import CONFIGURE, current_user, require

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

DEVICE_COLS = "id, profile_id, asset_id, name, point, config, online, last_seen, status_changed_at"


class SettingsChange(BaseModel):
    changes: dict
    reason: str | None = None


class ProfilePatch(BaseModel):
    telemetry_schema: dict | None = None
    default_settings: dict | None = None
    alarm_rules: list | None = None
    offline_after_s: int | None = None
    reason: str | None = None


@router.get("/assets")
async def assets(request: Request):
    return records(await request.app.state.pool.fetch("SELECT * FROM asset ORDER BY id"))


@router.get("/profiles")
async def profiles(request: Request):
    return records(await request.app.state.pool.fetch("SELECT * FROM device_profile ORDER BY id"))


@router.patch("/profiles/{profile_id}")
async def update_profile(profile_id: str, body: ProfilePatch, request: Request,
                         user: dict = Depends(require("admin", "owner"))):
    """The extensibility point: add telemetry keys, sensor kinds or alarm rules."""
    from ..engine import rules as r
    st = request.app.state
    old = await st.pool.fetchrow("SELECT * FROM device_profile WHERE id = $1", profile_id)
    if old is None:
        raise HTTPException(404, "no such profile")
    changes = body.model_dump(exclude_none=True, exclude={"reason"})
    try:
        for item in changes.get("alarm_rules", []):
            r.from_profile(profile_id, item)
    except (r.RuleError, KeyError, TypeError) as e:
        raise HTTPException(422, f"bad alarm rule: {e}") from None
    if not changes:
        raise HTTPException(400, "no changes")
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(changes, 2))
    await st.pool.execute(f"UPDATE device_profile SET {sets} WHERE id = $1", profile_id, *changes.values())
    await st.pool.execute(
        """INSERT INTO audit_log (username, entity, action, old, new, reason)
           VALUES ($1, $2, 'profile.update', $3, $4, $5)""",
        user["username"], f"profile:{profile_id}", {k: old[k] for k in changes}, changes, body.reason)
    await st.registry.load(st.pool)
    await st.engine.load_rules()
    return dict(await st.pool.fetchrow("SELECT * FROM device_profile WHERE id = $1", profile_id))


@router.get("/devices")
async def devices(request: Request):
    return records(await request.app.state.pool.fetch(f"SELECT {DEVICE_COLS} FROM device ORDER BY id"))


@router.get("/devices/{device_id}")
async def device(device_id: str, request: Request):
    pool = request.app.state.pool
    row = await pool.fetchrow(f"SELECT {DEVICE_COLS} FROM device WHERE id = $1", device_id)
    if row is None:
        raise HTTPException(404, "no such device")
    out = dict(row)
    out["sensors"] = records(await pool.fetch("SELECT * FROM sensor WHERE device_id = $1 ORDER BY id", device_id))
    out["attributes"] = records(await pool.fetch(
        "SELECT scope, key, value, updated_at FROM attribute WHERE entity_id = $1 ORDER BY scope, key", device_id))
    out["settings"] = await request.app.state.settings.state(device_id)
    return out


@router.get("/sensors")
async def sensors(request: Request, device_id: str | None = None, kind: str | None = None):
    return records(await request.app.state.pool.fetch(
        """SELECT * FROM sensor WHERE ($1::text IS NULL OR device_id = $1)
           AND ($2::text IS NULL OR kind = $2) ORDER BY id""", device_id, kind))


@router.get("/live")
async def live(request: Request):
    """Everything the dashboard needs on load; the WebSocket sends changes."""
    st = request.app.state
    pool = st.pool
    readings: dict[str, dict] = {}
    for r in await pool.fetch("SELECT sensor_id, key, ts, value FROM telemetry_latest"):
        readings.setdefault(r["sensor_id"], {})[r["key"]] = {"value": r["value"], "ts": r["ts"]}
    shared, client = {}, {}
    for r in await pool.fetch("SELECT entity_id, scope, key, value FROM attribute WHERE scope IN ('shared', 'client')"):
        (shared if r["scope"] == "shared" else client).setdefault(r["entity_id"], {})[r["key"]] = r["value"]
    return {
        "server_time": datetime.now(timezone.utc),
        "mqtt_connected": st.mqtt.connected,
        "devices": records(await pool.fetch(f"SELECT {DEVICE_COLS} FROM device ORDER BY id")),
        "sensors": records(await pool.fetch(
            "SELECT id, device_id, asset_id, kind, name, position, measuring FROM sensor ORDER BY id")),
        "readings": readings,
        "alarms": await st.alarms.open_alarms(),
        "settings": {d: {"desired": shared.get(d, {}), "reported": client.get(d, {}).get("settings")}
                     for d in st.registry.devices},
        "areas": await _areas(pool),
    }


async def _areas(pool) -> list[dict]:
    rows = await pool.fetch(
        """SELECT a.*, coalesce((SELECT json_agg(json_build_object('supplier_id', s.supplier_id, 'n_kg', s.n_kg))
                                 FROM supplier_area s WHERE s.cycle_id = a.cycle_id), '[]') AS suppliers
           FROM area_cycle_summary a WHERE a.unloaded_at IS NULL ORDER BY trough_no, area_no""")
    return records(rows)


@router.get("/areas")
async def areas(request: Request):
    """Trough areas currently loaded (open area cycles)."""
    return await _areas(request.app.state.pool)


@router.get("/history")
async def history(request: Request, sensor_id: list[str] = Query(...), key: str | None = None,
                  start: datetime | None = Query(None, alias="from"),
                  end: datetime | None = Query(None, alias="to"),
                  resolution: str = Query("auto", pattern="^(auto|raw|1m|1h)$")):
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=6)
    if start >= end:
        raise HTTPException(400, "from must be before to")
    ids = [s for item in sensor_id for s in item.split(",") if s]
    if resolution == "auto":
        span = end - start
        resolution = "raw" if span <= timedelta(hours=6) else "1m" if span <= timedelta(days=7) else "1h"
    if resolution == "raw":
        sql = """SELECT sensor_id, key, ts, value AS avg, value AS min, value AS max FROM telemetry
                 WHERE sensor_id = ANY($1) AND ($2::text IS NULL OR key = $2) AND ts >= $3 AND ts < $4
                 ORDER BY sensor_id, key, ts LIMIT 50000"""
    else:
        view = "telemetry_1m" if resolution == "1m" else "telemetry_1h"
        sql = f"""SELECT sensor_id, key, bucket AS ts, avg, min, max FROM {view}
                  WHERE sensor_id = ANY($1) AND ($2::text IS NULL OR key = $2) AND bucket >= $3 AND bucket < $4
                  ORDER BY sensor_id, key, bucket LIMIT 50000"""
    series: dict[tuple, list] = {}
    for r in await request.app.state.pool.fetch(sql, ids, key, start, end):
        series.setdefault((r["sensor_id"], r["key"]), []).append(
            [r["ts"], round(r["avg"], 3), round(r["min"], 3), round(r["max"], 3)])
    return {"from": start, "to": end, "resolution": resolution,
            "series": [{"sensor_id": s, "key": k, "points": p} for (s, k), p in series.items()]}


@router.get("/devices/{device_id}/settings")
async def get_settings(device_id: str, request: Request):
    if device_id not in request.app.state.registry.devices:
        raise HTTPException(404, "no such device")
    return await request.app.state.settings.state(device_id)


@router.put("/devices/{device_id}/settings")
async def put_settings(device_id: str, body: SettingsChange, request: Request,
                       user: dict = Depends(require(*CONFIGURE))):
    if device_id not in request.app.state.registry.devices:
        raise HTTPException(404, "no such device")
    try:
        return await request.app.state.settings.update(device_id, body.changes, user["username"], body.reason)
    except SettingsError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/ingest/stats")
async def ingest_stats(request: Request):
    st = request.app.state
    return {"since_start": dict(st.ingest.stats), "mqtt_connected": st.mqtt.connected,
            "websocket_clients": st.hub.count,
            "rejects_24h": await st.pool.fetchval(
                "SELECT count(*) FROM ingest_reject WHERE received_at > now() - interval '24 hours'")}


@router.get("/ingest/rejects")
async def ingest_rejects(request: Request, limit: int = Query(100, le=1000)):
    return records(await request.app.state.pool.fetch(
        "SELECT * FROM ingest_reject ORDER BY id DESC LIMIT $1", limit))
