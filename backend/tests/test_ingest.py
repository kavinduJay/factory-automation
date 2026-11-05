import json

from app.ingest.business import batch_by_time_window

NODE = "TF01-U-TR03-NOD01"
A, B, D = "TF01-U-RCV-SCB01", "TF01-U-WWB-SCB01", "TF01-L-DRO-SCB01"
_n = 0


def mid() -> str:
    global _n
    _n += 1
    return f"01TEST{_n:020d}"


def msg(**kw) -> bytes:
    kw.setdefault("msg_id", mid())
    kw.setdefault("ts", "2026-11-05T08:15:00.000Z")
    return json.dumps(kw).encode()


async def test_telemetry_written_and_deduplicated(stack):
    body = msg(readings=[{"sensor": "TF01-U-TR03-THS01", "t_c": 31.4, "rh_pct": 58.2},
                         {"sensor": "TF01-U-TR03-CTS01", "amp": 9.8, "run": True}])
    assert await stack.ingest.handle(f"tf01/{NODE}/telemetry", body) == "ok"
    assert await stack.ingest.handle(f"tf01/{NODE}/telemetry", body) == "duplicate"
    assert await stack.pool.fetchval("SELECT count(*) FROM telemetry") == 4
    latest = await stack.pool.fetchval(
        "SELECT value FROM telemetry_latest WHERE sensor_id = 'TF01-U-TR03-THS01' AND key = 't_c'")
    assert latest == 31.4
    assert await stack.pool.fetchval(f"SELECT online FROM device WHERE id = '{NODE}'")
    assert len(stack.hub.of("telemetry")) == 1


async def test_bad_readings_rejected_good_kept(stack):
    body = msg(readings=[{"sensor": "TF01-U-TR03-THS01", "t_c": 31.0, "rh_pct": 140}])
    assert await stack.ingest.handle(f"tf01/{NODE}/telemetry", body) == "partial"
    assert await stack.pool.fetchval("SELECT count(*) FROM telemetry") == 1
    assert await stack.pool.fetchval("SELECT count(*) FROM ingest_reject") == 1


async def test_unknown_device_and_bad_json(stack):
    assert await stack.ingest.handle("tf01/TF01-U-TR99-NOD01/telemetry", msg(readings=[])) == "rejected"
    assert await stack.ingest.handle(f"tf01/{NODE}/telemetry", b"{not json") == "rejected"
    assert await stack.pool.fetchval("SELECT count(*) FROM ingest_reject") == 2


async def test_status_offline_raises_and_online_clears(stack):
    await stack.ingest.handle(f"tf01/{NODE}/telemetry",
                              msg(readings=[{"sensor": "TF01-U-TR03-THS01", "t_c": 30}]))
    await stack.ingest.handle(f"tf01/{NODE}/status", b"offline")
    assert await stack.pool.fetchval(
        "SELECT status FROM alarm WHERE entity_id = $1 AND type = 'offline'", NODE) == "active"
    await stack.ingest.handle(f"tf01/{NODE}/status", b"online")
    assert await stack.pool.fetchval(
        "SELECT status FROM alarm WHERE entity_id = $1 AND type = 'offline'", NODE) == "cleared"


async def test_sack_crate_flow(stack):
    h = stack.ingest.handle
    for seq, net in enumerate((34.0, 35.0, 33.0), 1):
        assert await h(f"tf01/{A}/event", msg(
            type="sack_weighed", supplier_id="SUP-007", delivery_id="DLV-1", sack_seq=seq,
            gross_kg=net + 1, sack_tare_kg=1.0, net_kg=net, trough_no=3, area_no=5, stable=True)) == "ok"
    cycle = await stack.pool.fetchrow("SELECT * FROM area_cycle")
    assert cycle["trough_no"] == 3 and cycle["unloaded_at"] is None
    assert await stack.pool.fetchval("SELECT auto_created FROM supplier WHERE id = 'SUP-007'")

    # Over the limit (25 kg default): not recorded, alarm raised.
    await h(f"tf01/{B}/event", msg(type="crate_weighed", trough_no=3, area_no=5, crate_id="CR-1",
                                   net_kg=26.0, over_limit=True, stable=True, batch_id="B1"))
    assert await stack.pool.fetchval("SELECT count(*) FROM crate_weighing") == 0
    assert await stack.pool.fetchval(
        "SELECT count(*) FROM alarm WHERE type = 'over_limit' AND cleared_at IS NULL") == 1
    # Re-weighed lighter: recorded, alarm cleared.
    for net in (19.0, 19.0, 18.0):
        await h(f"tf01/{B}/event", msg(type="crate_weighed", trough_no=3, area_no=5, crate_id="CR-1",
                                       net_kg=net, stable=True, batch_id="B1"))
    assert await stack.pool.fetchval("SELECT sum(net_kg) FROM crate_weighing WHERE cycle_id = $1",
                                     cycle["id"]) == 56
    assert await stack.pool.fetchval(
        "SELECT count(*) FROM alarm WHERE type = 'over_limit' AND cleared_at IS NULL") == 0
    await h(f"tf01/{B}/event", msg(type="area_unloaded", trough_no=3, area_no=5))
    assert await stack.pool.fetchval("SELECT unloaded_at FROM area_cycle WHERE id = $1", cycle["id"])
    # Unstable weight rejected.
    assert await h(f"tf01/{B}/event", msg(type="crate_weighed", trough_no=3, area_no=5,
                                          net_kg=10.0, stable=False)) == "rejected"


async def test_weighings_are_append_only(stack):
    await stack.ingest.handle(f"tf01/{A}/event", msg(
        type="sack_weighed", supplier_id="SUP-001", gross_kg=20, net_kg=19, trough_no=1, area_no=1))
    import asyncpg
    import pytest
    with pytest.raises(asyncpg.RestrictViolationError, match="append-only"):
        await stack.pool.execute("UPDATE sack_weighing SET net_kg = 1")
    with pytest.raises(asyncpg.RestrictViolationError, match="append-only"):
        await stack.pool.execute("DELETE FROM sack_weighing")


async def test_stage_validation_and_drier_time_window(stack):
    h = stack.ingest.handle
    await h(f"tf01/{B}/event", msg(type="crate_weighed", trough_no=1, area_no=1, net_kg=20.0, batch_id="B9"))
    await h("tf01/TF01-L-RW1-SCB01/event", msg(type="stage_weighed", batch_id="B9", net_kg=25.0))
    assert await stack.pool.fetchval(
        "SELECT severity FROM alarm WHERE entity_id = 'B9' AND type = 'w1_exceeds_previous'") == "warning"
    await h("tf01/TF01-L-RW3-SCB01/event", msg(type="stage_weighed", batch_id="B9", net_kg=10.0,
                                                bulk=True, ts="2026-11-05T09:00:00Z"))
    b = await stack.pool.fetchrow("SELECT * FROM batch WHERE id = 'B9'")
    assert b["bulk_stage"] == 3 and b["status"] == "fermenting"
    # 09:00 + 150 min fermentation + 21 min drying = 11:51
    assert await h(f"tf01/{D}/event", msg(type="drier_output", net_kg=4.4,
                                          ts="2026-11-05T11:55:00Z")) == "ok"
    row = await stack.pool.fetchrow("SELECT batch_id, batch_assigned FROM drier_output")
    assert (row["batch_id"], row["batch_assigned"]) == ("B9", "time_window")
    async with stack.pool.acquire() as c:
        assert await batch_by_time_window(c, __import__("datetime").datetime.fromisoformat(
            "2026-11-06T11:55:00+00:00")) is None
