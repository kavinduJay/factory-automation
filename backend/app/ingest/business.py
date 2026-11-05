"""Turns validated weighing events into business records (docs/PROCESS.md).

Called inside the ingest transaction, after the raw event is in event_log.
"""
from datetime import datetime, timedelta

from ..alarms import AlarmService


async def record_event(c, alarms: AlarmService, device: dict, msg_id: str,
                       ts: datetime, ev: dict) -> dict:
    handler = {
        "sack_weighed": _sack,
        "crate_weighed": _crate,
        "area_unloaded": _area_unloaded,
        "stage_weighed": _stage,
        "drier_output": _drier,
    }[ev["type"]]
    return await handler(c, alarms, device, msg_id, ts, ev)


# -- helpers -----------------------------------------------------------------

async def _shared(c, device_id: str, key: str):
    return await c.fetchval(
        "SELECT value FROM attribute WHERE entity_id = $1 AND scope = 'shared' AND key = $2",
        device_id, key)


async def _site_setting(c, key: str, default):
    v = await c.fetchval(
        "SELECT value FROM attribute WHERE entity_id = 'TF01' AND scope = 'server' AND key = $1", key)
    return default if v is None else v


async def _open_cycle(c, trough: int, area: int, ts: datetime) -> int:
    cid = await c.fetchval(
        "SELECT id FROM area_cycle WHERE trough_no = $1 AND area_no = $2 AND unloaded_at IS NULL",
        trough, area)
    if cid is None:
        cid = await c.fetchval(
            "INSERT INTO area_cycle (trough_no, area_no, loaded_at) VALUES ($1, $2, $3) RETURNING id",
            trough, area, ts)
    return cid


async def _ensure_batch(c, batch_id: str, ts: datetime) -> None:
    await c.execute(
        "INSERT INTO batch (id, opened_at) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", batch_id, ts)


async def _limit_check(c, alarms, device, ev, entity_type: str) -> tuple[bool, float | None]:
    limit = ev.get("max_limit_kg")
    if limit is None:
        limit = await _shared(c, device["id"], "max_limit_kg")
    over = bool(ev.get("over_limit")) or (limit is not None and float(ev["net_kg"]) > float(limit))
    if over:
        await alarms.raise_(
            conn=c, entity_id=device["id"], device_id=device["id"], type="over_limit",
            severity="warning",
            message=f"{entity_type} over limit at {device['point']}: {ev['net_kg']} kg > {limit} kg",
            details={"net_kg": ev["net_kg"], "max_limit_kg": limit, "crate_id": ev.get("crate_id")})
    else:
        await alarms.clear(conn=c, entity_id=device["id"], type="over_limit")
    return over, limit


# -- A: sack ------------------------------------------------------------------

async def _sack(c, alarms, device, msg_id, ts, ev) -> dict:
    supplier = str(ev["supplier_id"])
    await c.execute(
        "INSERT INTO supplier (id, name, auto_created) VALUES ($1, $1, true) ON CONFLICT (id) DO NOTHING",
        supplier)
    delivery = ev.get("delivery_id")
    if delivery:
        await c.execute(
            """INSERT INTO delivery (id, supplier_id, device_id, started_at) VALUES ($1, $2, $3, $4)
               ON CONFLICT (id) DO NOTHING""", delivery, supplier, device["id"], ts)
    trough, area = ev["trough_no"], ev["area_no"]
    # Loading into an area that has already been partly unloaded at B starts
    # a new cycle.
    open_id = await c.fetchval(
        "SELECT id FROM area_cycle WHERE trough_no = $1 AND area_no = $2 AND unloaded_at IS NULL",
        trough, area)
    if open_id and await c.fetchval("SELECT 1 FROM crate_weighing WHERE cycle_id = $1 LIMIT 1", open_id):
        await c.execute("UPDATE area_cycle SET unloaded_at = $2 WHERE id = $1", open_id, ts)
    cycle_id = await _open_cycle(c, trough, area, ts)
    sack_id = await c.fetchval(
        """INSERT INTO sack_weighing (msg_id, ts, device_id, delivery_id, supplier_id, sack_seq,
               gross_kg, sack_tare_kg, wet_deduction_kg, coarse_deduction_kg, net_kg,
               trough_no, area_no, cycle_id, maturity, photos, operator_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
           RETURNING id""",
        msg_id, ts, device["id"], delivery, supplier, ev.get("sack_seq"),
        ev["gross_kg"], ev.get("sack_tare_kg", 0), ev.get("wet_deduction_kg", 0),
        ev.get("coarse_deduction_kg", 0), ev["net_kg"], trough, area, cycle_id,
        ev.get("maturity"), ev.get("photos", []), ev.get("operator_id"))
    return {"record": "sack_weighing", "id": sack_id, "cycle_id": cycle_id}


# -- B: crate -----------------------------------------------------------------

async def _crate(c, alarms, device, msg_id, ts, ev) -> dict:
    over, limit = await _limit_check(c, alarms, device, ev, "Crate")
    if over:
        # Not recorded: the operator lightens the crate and weighs again.
        return {"record": None, "over_limit": True, "max_limit_kg": limit}
    cycle_id = await _open_cycle(c, ev["trough_no"], ev["area_no"], ts)
    batch_id = ev.get("batch_id")
    if batch_id:
        await _ensure_batch(c, batch_id, ts)
    crate_id = await c.fetchval(
        """INSERT INTO crate_weighing (msg_id, ts, device_id, cycle_id, trough_no, area_no, crate_id,
               gross_kg, tare_kg, net_kg, max_limit_kg, batch_id, operator_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) RETURNING id""",
        msg_id, ts, device["id"], cycle_id, ev["trough_no"], ev["area_no"], ev.get("crate_id"),
        ev.get("gross_kg"), ev.get("tare_kg"), ev["net_kg"], limit, batch_id, ev.get("operator_id"))
    return {"record": "crate_weighing", "id": crate_id, "cycle_id": cycle_id, "batch_id": batch_id}


async def _area_unloaded(c, alarms, device, msg_id, ts, ev) -> dict:
    cid = await c.fetchval(
        """UPDATE area_cycle SET unloaded_at = $3
           WHERE trough_no = $1 AND area_no = $2 AND unloaded_at IS NULL RETURNING id""",
        ev["trough_no"], ev["area_no"], ts)
    return {"record": "area_cycle", "id": cid}


# -- W1..W4: rolling stages ------------------------------------------------------

async def stage_totals(c, batch_id: str) -> dict:
    wz = await c.fetchval(
        "SELECT coalesce(sum(net_kg), 0) FROM crate_weighing_effective WHERE batch_id = $1", batch_id)
    rows = await c.fetch(
        "SELECT stage, sum(net_kg) AS kg FROM stage_weighing_effective WHERE batch_id = $1 GROUP BY stage",
        batch_id)
    out = {0: float(wz)}
    out.update({r["stage"]: float(r["kg"]) for r in rows})
    return out


async def _stage(c, alarms, device, msg_id, ts, ev) -> dict:
    batch_id, stage = str(ev["batch_id"]), ev["stage"]
    await _ensure_batch(c, batch_id, ts)
    bulk = bool(ev.get("bulk"))
    sid = await c.fetchval(
        """INSERT INTO stage_weighing (msg_id, ts, device_id, batch_id, stage, net_kg, bulk, operator_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
        msg_id, ts, device["id"], batch_id, stage, ev["net_kg"], bulk, ev.get("operator_id"))
    if bulk:
        await c.execute(
            """UPDATE batch SET bulk_stage = $2, fermentation_start = coalesce(fermentation_start, $3),
                   status = CASE WHEN status IN ('withered', 'rolling') THEN 'fermenting' ELSE status END
               WHERE id = $1""", batch_id, stage, ts)
    else:
        await c.execute("UPDATE batch SET status = 'rolling' WHERE id = $1 AND status = 'withered'", batch_id)

    # Validation: each Wn <= W(n-1), W1 <= Wz. A larger value raises a warning.
    totals = await stage_totals(c, batch_id)
    prev, cur = totals.get(stage - 1, 0.0), totals.get(stage, 0.0)
    if prev > 0 and cur > prev:
        label = "Wz" if stage == 1 else f"W{stage - 1}"
        await alarms.raise_(
            conn=c, entity_id=batch_id, device_id=device["id"], type=f"w{stage}_exceeds_previous",
            severity="warning", message=f"Batch {batch_id}: W{stage} {cur:g} kg > {label} {prev:g} kg",
            details={"stage": stage, "w": cur, "previous": prev})
    return {"record": "stage_weighing", "id": sid, "batch_id": batch_id, "stage": stage}


# -- D: drier output -------------------------------------------------------------

async def batch_by_time_window(c, ts: datetime) -> str | None:
    """Batch whose fermentation start + fermentation time + drying time is
    closest to ts, within the window (docs/PROCESS.md)."""
    ferm = float(await _site_setting(c, "fermentation_minutes", 150))
    dry = float(await _site_setting(c, "drying_minutes", 21))
    window = float(await _site_setting(c, "batch_window_minutes", 90))
    return await c.fetchval(
        """SELECT id FROM batch
           WHERE fermentation_start IS NOT NULL AND fermentation_start <= $1
             AND abs(extract(epoch FROM ($1 - (fermentation_start + $2 * interval '1 minute')))) <= $3 * 60
           ORDER BY abs(extract(epoch FROM ($1 - (fermentation_start + $2 * interval '1 minute'))))
           LIMIT 1""", ts, ferm + dry, window)


async def _drier(c, alarms, device, msg_id, ts, ev) -> dict:
    over, limit = await _limit_check(c, alarms, device, ev, "Made tea")
    if over:
        return {"record": None, "over_limit": True, "max_limit_kg": limit}
    batch_id, assigned = ev.get("batch_id"), "device"
    if batch_id:
        await _ensure_batch(c, batch_id, ts)
    else:
        batch_id, assigned = await batch_by_time_window(c, ts), "time_window"
    did = await c.fetchval(
        """INSERT INTO drier_output (msg_id, ts, device_id, batch_id, batch_assigned, net_kg,
               moisture_pct, max_limit_kg, operator_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
        msg_id, ts, device["id"], batch_id, assigned, ev["net_kg"], ev.get("moisture_pct"),
        limit, ev.get("operator_id"))
    if batch_id:
        dry = float(await _site_setting(c, "drying_minutes", 21))
        await c.execute(
            """UPDATE batch SET status = 'drying',
                   fermentation_end = coalesce(fermentation_end, $2)
               WHERE id = $1 AND status <> 'done'""", batch_id, ts - timedelta(minutes=dry))
    return {"record": "drier_output", "id": did, "batch_id": batch_id, "batch_assigned": assigned}
