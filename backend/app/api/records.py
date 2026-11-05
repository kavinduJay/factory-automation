"""Business records: weighings (with corrections), batches, reports, events."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..db import records
from .auth import CONFIGURE, current_user, require

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

KINDS = {"sack": "sack_weighing", "crate": "crate_weighing",
         "stage": "stage_weighing", "drier": "drier_output"}
# Fields a correction may change, per kind. Trough/area of a sack or crate is
# not correctable here because it decides the area cycle.
CORRECTABLE = {
    "sack": {"supplier_id", "gross_kg", "sack_tare_kg", "wet_deduction_kg", "coarse_deduction_kg",
             "net_kg", "maturity"},
    "crate": {"net_kg", "gross_kg", "tare_kg", "crate_id", "batch_id"},
    "stage": {"net_kg", "stage", "bulk", "batch_id"},
    "drier": {"net_kg", "moisture_pct", "batch_id"},
}
NOT_COPIED = {"id", "msg_id", "created_at", "corrects_id", "voided", "reason", "created_by"}


class Correction(BaseModel):
    changes: dict = Field(default_factory=dict)
    voided: bool = False
    reason: str = Field(min_length=3)


class BatchPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(withered|rolling|fermenting|drying|done)$")
    notes: str | None = None
    bulk_stage: int | None = Field(default=None, ge=3, le=4)
    fermentation_start: datetime | None = None
    fermentation_end: datetime | None = None
    reason: str | None = None


def _table(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(404, f"kind must be one of {', '.join(KINDS)}")
    return KINDS[kind]


@router.get("/weighings/{kind}")
async def weighings(kind: str, request: Request,
                    start: datetime | None = Query(None, alias="from"),
                    end: datetime | None = Query(None, alias="to"),
                    batch_id: str | None = None, supplier_id: str | None = None,
                    trough_no: int | None = None, history: bool = False,
                    limit: int = Query(200, le=5000)):
    """Effective weighings (latest correction applied, voided removed), or with
    history=true every stored row including originals and corrections."""
    table = _table(kind)
    src = table if history else f"{table}_effective"
    where, args = ["($1::timestamptz IS NULL OR ts >= $1)", "($2::timestamptz IS NULL OR ts < $2)"], [start, end]
    for col, val in (("batch_id", batch_id), ("supplier_id", supplier_id), ("trough_no", trough_no)):
        if val is not None:
            if col == "supplier_id" and kind != "sack" or col == "trough_no" and kind not in ("sack", "crate") \
                    or col == "batch_id" and kind == "sack":
                raise HTTPException(400, f"{col} does not apply to {kind}")
            args.append(val)
            where.append(f"{col} = ${len(args)}")
    args.append(limit)
    return records(await request.app.state.pool.fetch(
        f"SELECT * FROM {src} WHERE {' AND '.join(where)} ORDER BY ts DESC, id DESC LIMIT ${len(args)}", *args))


@router.post("/weighings/{kind}/{record_id}/correct", status_code=201)
async def correct(kind: str, record_id: int, body: Correction, request: Request,
                  user: dict = Depends(require(*CONFIGURE))):
    """Never overwrite a weighing: insert a new row that references the original."""
    table = _table(kind)
    bad = set(body.changes) - CORRECTABLE[kind]
    if bad:
        raise HTTPException(422, f"cannot correct {', '.join(sorted(bad))} on a {kind} weighing")
    if not body.changes and not body.voided:
        raise HTTPException(422, "give changes or voided=true")
    pool = request.app.state.pool
    async with pool.acquire() as c, c.transaction():
        row = await c.fetchrow(f"SELECT id, corrects_id FROM {table} WHERE id = $1", record_id)
        if row is None:
            raise HTTPException(404, "no such weighing")
        original_id = row["corrects_id"] or row["id"]
        latest = dict(await c.fetchrow(
            f"SELECT * FROM {table} WHERE id = $1 OR corrects_id = $1 ORDER BY id DESC LIMIT 1", original_id))
        new = {k: v for k, v in latest.items() if k not in NOT_COPIED}
        new.update(body.changes)
        if kind == "sack" and "net_kg" not in body.changes and \
                body.changes.keys() & {"gross_kg", "sack_tare_kg", "wet_deduction_kg", "coarse_deduction_kg"}:
            new["net_kg"] = (float(new["gross_kg"]) - float(new["sack_tare_kg"])
                             - float(new["wet_deduction_kg"]) - float(new["coarse_deduction_kg"]))
        for k in ("net_kg", "gross_kg", "tare_kg", "sack_tare_kg", "wet_deduction_kg", "coarse_deduction_kg"):
            if k in new and new[k] is not None and float(new[k]) < 0:
                raise HTTPException(422, f"{k} cannot be negative")
        if body.changes.get("batch_id"):
            if not await c.fetchval("SELECT 1 FROM batch WHERE id = $1", body.changes["batch_id"]):
                raise HTTPException(422, "no such batch")
        if kind == "sack" and "supplier_id" in body.changes:
            if not await c.fetchval("SELECT 1 FROM supplier WHERE id = $1", body.changes["supplier_id"]):
                raise HTTPException(422, "no such supplier")
        if kind == "drier" and "batch_id" in body.changes:
            new["batch_assigned"] = "operator"
        new.update(corrects_id=original_id, voided=body.voided, reason=body.reason, created_by=user["username"])
        cols = list(new)
        inserted = await c.fetchrow(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(f'${i}' for i in range(1, len(cols) + 1))}) "
            "RETURNING *", *new.values())
        await c.execute(
            """INSERT INTO audit_log (username, entity, action, old, new, reason)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            user["username"], f"{table}:{original_id}", "weighing.void" if body.voided else "weighing.correct",
            {k: latest.get(k) for k in body.changes}, {**body.changes, "voided": body.voided}, body.reason)
    out = dict(inserted)
    await request.app.state.hub.broadcast({"type": "correction", "kind": kind, "record": out})
    return out


@router.get("/batches")
async def batches(request: Request, status: str | None = None, limit: int = Query(50, le=1000)):
    return records(await request.app.state.pool.fetch(
        """SELECT * FROM batch_summary WHERE ($1::text IS NULL OR status = $1)
           ORDER BY opened_at DESC LIMIT $2""", status, limit))


@router.get("/batches/{batch_id}")
async def batch(batch_id: str, request: Request):
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT * FROM batch_summary WHERE batch_id = $1", batch_id)
    if row is None:
        raise HTTPException(404, "no such batch")
    return {**dict(row),
            "suppliers": records(await pool.fetch(
                "SELECT * FROM supplier_batch_attribution WHERE batch_id = $1 ORDER BY bw_kg DESC", batch_id)),
            "stages": records(await pool.fetch(
                "SELECT * FROM stage_weighing_effective WHERE batch_id = $1 ORDER BY ts", batch_id)),
            "drier": records(await pool.fetch(
                "SELECT * FROM drier_output_effective WHERE batch_id = $1 ORDER BY ts", batch_id))}


@router.patch("/batches/{batch_id}")
async def patch_batch(batch_id: str, body: BatchPatch, request: Request,
                      user: dict = Depends(require(*CONFIGURE))):
    pool = request.app.state.pool
    changes = body.model_dump(exclude_none=True, exclude={"reason"})
    if not changes:
        raise HTTPException(400, "no changes")
    old = await pool.fetchrow("SELECT * FROM batch WHERE id = $1", batch_id)
    if old is None:
        raise HTTPException(404, "no such batch")
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(changes, 2))
    await pool.execute(f"UPDATE batch SET {sets} WHERE id = $1", batch_id, *changes.values())
    await pool.execute(
        """INSERT INTO audit_log (username, entity, action, old, new, reason)
           VALUES ($1, $2, 'batch.update', $3, $4, $5)""",
        user["username"], f"batch:{batch_id}", {k: old[k] for k in changes}, changes, body.reason)
    return dict(await pool.fetchrow("SELECT * FROM batch_summary WHERE batch_id = $1", batch_id))


@router.get("/suppliers")
async def suppliers(request: Request):
    return records(await request.app.state.pool.fetch("SELECT * FROM supplier ORDER BY id"))


@router.get("/reports/moisture-loss")
async def moisture_loss(request: Request, start: date | None = Query(None, alias="from"),
                        end: date | None = Query(None, alias="to"), supplier_id: str | None = None):
    return records(await request.app.state.pool.fetch(
        """SELECT * FROM moisture_loss_supplier
           WHERE ($1::date IS NULL OR day >= $1) AND ($2::date IS NULL OR day <= $2)
             AND ($3::text IS NULL OR supplier_id = $3)
           ORDER BY day DESC, supplier_id""", start, end, supplier_id))


@router.get("/reports/supplier-attribution")
async def supplier_attribution(request: Request, batch_id: str | None = None, supplier_id: str | None = None,
                               limit: int = Query(500, le=5000)):
    return records(await request.app.state.pool.fetch(
        """SELECT a.*, b.opened_at, b.status FROM supplier_batch_attribution a
           JOIN batch_summary b USING (batch_id)
           WHERE ($1::text IS NULL OR a.batch_id = $1) AND ($2::text IS NULL OR a.supplier_id = $2)
           ORDER BY b.opened_at DESC, a.bw_kg DESC LIMIT $3""", batch_id, supplier_id, limit))


@router.get("/reports/areas")
async def area_report(request: Request, limit: int = Query(200, le=5000)):
    return records(await request.app.state.pool.fetch(
        "SELECT * FROM area_cycle_summary ORDER BY loaded_at DESC LIMIT $1", limit))


@router.get("/events")
async def events(request: Request, device_id: str | None = None, type: str | None = None,
                 limit: int = Query(100, le=1000)):
    return records(await request.app.state.pool.fetch(
        """SELECT * FROM event_log WHERE ($1::text IS NULL OR device_id = $1) AND ($2::text IS NULL OR type = $2)
           ORDER BY ts DESC LIMIT $3""", device_id, type, limit))


@router.get("/summary")
async def summary(request: Request):
    """Today's totals (factory-local day, Asia/Colombo) for the overview."""
    row = await request.app.state.pool.fetchrow("""
        WITH d AS (SELECT date_trunc('day', now() AT TIME ZONE 'Asia/Colombo') AT TIME ZONE 'Asia/Colombo' AS start)
        SELECT (SELECT count(*) FROM sack_weighing_effective, d WHERE ts >= d.start)                   AS sacks,
               (SELECT coalesce(sum(net_kg), 0) FROM sack_weighing_effective, d WHERE ts >= d.start)  AS green_leaf_kg,
               (SELECT count(*) FROM crate_weighing_effective, d WHERE ts >= d.start)                 AS crates,
               (SELECT coalesce(sum(net_kg), 0) FROM crate_weighing_effective, d WHERE ts >= d.start) AS withered_kg,
               (SELECT count(*) FROM batch, d WHERE opened_at >= d.start)                             AS batches,
               (SELECT coalesce(sum(net_kg), 0) FROM drier_output_effective, d WHERE ts >= d.start)   AS made_tea_kg""")
    return dict(row)
