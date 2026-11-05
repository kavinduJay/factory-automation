"""The worked example from docs/PROCESS.md, fed through ingest as device
events, then read back from the report views."""
import json
from decimal import Decimal

import pytest

A, B, D = "TF01-U-RCV-SCB01", "TF01-U-WWB-SCB01", "TF01-L-DRO-SCB01"
_n = 0


def ev(**kw) -> bytes:
    global _n
    _n += 1
    kw.setdefault("msg_id", f"01REPORT{_n:018d}")
    kw.setdefault("ts", "2026-11-05T06:00:00Z")
    kw.setdefault("stable", True)
    return json.dumps(kw).encode()


async def sack(h, supplier, net, trough, area, ts="2026-11-05T06:00:00Z"):
    await h(f"tf01/{A}/event", ev(type="sack_weighed", supplier_id=supplier, gross_kg=net + 1,
                                  sack_tare_kg=1, net_kg=net, trough_no=trough, area_no=area, ts=ts))


async def crate(h, net, trough, area, batch, ts="2026-11-05T14:00:00Z"):
    assert await h(f"tf01/{B}/event", ev(type="crate_weighed", trough_no=trough, area_no=area,
                                         net_kg=net, batch_id=batch, ts=ts)) == "ok"


@pytest.fixture
async def worked_example(stack):
    h = stack.ingest.handle
    # A: SUP-007, 3 sacks, 102 kg net into trough 3, area 5
    for net in (34, 35, 33):
        await sack(h, "SUP-007", net, 3, 5)
    # The rest of the batch: 698 kg green leaf from SUP-008 in trough 4,
    # areas 1-7 (99.71 kg each, rounded) -> 344 kg withered.
    for area in range(1, 8):
        await sack(h, "SUP-008", 100 if area < 7 else 98, 4, area)
    # B: 3 crates from T3-A5, 56 kg
    for net in (19, 19, 18):
        await crate(h, net, 3, 5, "B1")
    for area in range(1, 8):  # 2 crates per area, under the 25 kg limit
        for _ in range(2):
            await crate(h, 24.5 if area < 7 else 25, 4, area, "B1")
    for t, a in [(3, 5)] + [(4, x) for x in range(1, 8)]:
        await h(f"tf01/{B}/event", ev(type="area_unloaded", trough_no=t, area_no=a,
                                      ts="2026-11-05T14:30:00Z"))
    # Rolling: W1 300, W2 220, W3 160 marked bulk
    await h("tf01/TF01-L-RW1-SCB01/event", ev(type="stage_weighed", batch_id="B1", net_kg=300))
    await h("tf01/TF01-L-RW2-SCB01/event", ev(type="stage_weighed", batch_id="B1", net_kg=220))
    await h("tf01/TF01-L-RW3-SCB01/event", ev(type="stage_weighed", batch_id="B1", net_kg=160, bulk=True))
    # D: 176 kg made tea, in 8 loads of 22 kg (under the 30 kg limit)
    for _ in range(8):
        assert await h(f"tf01/{D}/event", ev(type="drier_output", batch_id="B1", net_kg=22)) == "ok"
    return stack


async def test_moisture_loss(worked_example):
    p = worked_example.pool
    row = await p.fetchrow("SELECT * FROM moisture_loss_supplier WHERE supplier_id = 'SUP-007'")
    assert row["n_kg"] == 102 and row["bw_kg"] == 56
    assert row["moisture_loss_pct"] == Decimal("45.10")       # (102 - 56) / 102
    assert row["estimated"] is False


async def test_batch_dhool_and_out_turn(worked_example):
    b = await worked_example.pool.fetchrow("SELECT * FROM batch_summary WHERE batch_id = 'B1'")
    assert b["wz_kg"] == 400 and b["green_leaf_kg"] == 800
    assert (b["ws1_kg"], b["ws2_kg"], b["ws3_kg"]) == (100, 80, 60)
    assert b["ws4_kg"] is None and b["bulk_stage"] == 3 and b["bulk_kg"] == 160
    assert b["out_turn_pct"] == Decimal("22.00")              # 176 / 800
    assert b["warnings"] == []
    assert b["status"] == "drying"


async def test_supplier_attribution(worked_example):
    s = await worked_example.pool.fetchrow(
        "SELECT * FROM supplier_batch_attribution WHERE batch_id = 'B1' AND supplier_id = 'SUP-007'")
    assert s["share_pct"] == Decimal("14.00")                 # 56 / 400
    assert s["made_tea_kg"] == Decimal("24.640")              # 176 x 14 %, about 25 kg
    assert s["made_tea_estimated"] and not s["bw_estimated"]


async def test_correction_changes_reports_not_history(worked_example):
    p = worked_example.pool
    orig = await p.fetchrow("SELECT * FROM crate_weighing WHERE trough_no = 3 ORDER BY id LIMIT 1")
    await p.execute(
        """INSERT INTO crate_weighing (ts, device_id, cycle_id, trough_no, area_no, net_kg, batch_id,
               corrects_id, reason, created_by)
           VALUES ($1, $2, $3, 3, 5, 20, 'B1', $4, 'misread', 'test')""",
        orig["ts"], orig["device_id"], orig["cycle_id"], orig["id"])
    assert await p.fetchval("SELECT bw_kg FROM area_cycle_summary WHERE cycle_id = $1", orig["cycle_id"]) == 57
    assert await p.fetchval("SELECT count(*) FROM crate_weighing WHERE cycle_id = $1", orig["cycle_id"]) == 4
    # A correction of a correction is refused; it must point at the original.
    corr = await p.fetchval("SELECT max(id) FROM crate_weighing")
    with pytest.raises(Exception, match="original"):
        await p.execute(
            """INSERT INTO crate_weighing (ts, cycle_id, trough_no, area_no, net_kg, corrects_id)
               VALUES (now(), $1, 3, 5, 21, $2)""", orig["cycle_id"], corr)


async def test_mixed_area_is_estimated(stack):
    h = stack.ingest.handle
    await sack(h, "SUP-001", 60, 5, 1)
    await sack(h, "SUP-002", 40, 5, 1)
    await crate(h, 25, 5, 1, "B2")
    await crate(h, 25, 5, 1, "B2")
    await h(f"tf01/{B}/event", ev(type="area_unloaded", trough_no=5, area_no=1))
    rows = {r["supplier_id"]: r for r in await stack.pool.fetch("SELECT * FROM supplier_area")}
    assert rows["SUP-001"]["bw_kg"] == 30 and rows["SUP-002"]["bw_kg"] == 20
    assert rows["SUP-001"]["estimated"]
    sb = {r["supplier_id"]: r for r in await stack.pool.fetch(
        "SELECT * FROM supplier_batch_attribution WHERE batch_id = 'B2'")}
    assert sb["SUP-001"]["share_pct"] == 60 and sb["SUP-001"]["bw_estimated"]
