"""Leaf flow on a compressed clock (SIM_SPEED x real time), per docs/PROCESS.md:

  A  suppliers' sacks into trough areas (one scale, one sack at a time)
     ~8 h withering
  B  areas unloaded into crates (one scale), crates assigned to a batch of
     ~400 kg (Wz); some crates are overfilled, rejected and re-weighed
  W1..W3 (or W4) rolling stages, last one marked bulk
     ~2.5 h fermentation, ~21 min drying
  D  made tea, about 22 % of the green leaf, in loads under the D limit
"""
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone

from .client import DeviceClient
from .plant import Plant
from .ulid import ulid

log = logging.getLogger(__name__)

A, B, D = "TF01-U-RCV-SCB01", "TF01-U-WWB-SCB01", "TF01-L-DRO-SCB01"
W = {1: "TF01-L-RW1-SCB01", 2: "TF01-L-RW2-SCB01", 3: "TF01-L-RW3-SCB01", 4: "TF01-L-RW4-SCB01"}
ROLLERS = {1: ("RC1", "RC2", "RC3"), 2: ("R21", "R22", "R23"), 3: ("R31", "R32"), 4: ("R41",)}
SUPPLIERS = [f"SUP-{n:03d}" for n in range(1, 41)]
OPERATORS = [f"OP{n:02d}" for n in range(1, 13)]
COLOMBO = timezone(timedelta(hours=5, minutes=30))

MIN = 60.0
HOUR = 3600.0


class Process:
    def __init__(self, plant: Plant, clients: dict[str, DeviceClient], speed: float) -> None:
        self.plant, self.c, self.speed = plant, clients, speed
        self.lock_a, self.lock_b, self.lock_d = asyncio.Lock(), asyncio.Lock(), asyncio.Lock()
        self.area_n: dict[tuple[int, int], float] = {}
        self.batch_id = self._new_batch_id()
        self.batch_wz = 0.0
        self.batch_target = random.uniform(360, 440)
        self.counts = {"sacks": 0, "crates": 0, "over_limit": 0, "batches": 0, "made_tea_kg": 0.0}

    async def psleep(self, process_s: float) -> None:
        await asyncio.sleep(process_s / self.speed)

    def _new_batch_id(self) -> str:
        return f"B{datetime.now(COLOMBO):%Y%m%d}-{ulid()[-4:]}"

    # -- troughs -----------------------------------------------------------------

    async def trough_cycle(self, no: int, start_progress: float) -> None:
        tr = self.plant.troughs[no]
        first = True
        while True:
            await self.load(no, quick=first)
            wither = random.uniform(7.5, 8.5) * HOUR
            tr.state, tr.progress = "withering", start_progress if first else 0.0
            first = False
            while tr.progress < 1:
                await self.psleep(10 * MIN)
                tr.progress = min(1.0, tr.progress + 10 * MIN / wither)
            tr.state = "waiting"
            async with self.lock_b:
                tr.state = "unloading"
                await self.unload(no)
            tr.state, tr.progress = "empty", 0.0
            await self.psleep(random.uniform(5, 20) * MIN)

    async def load(self, no: int, quick: bool = False) -> None:
        tr = self.plant.troughs[no]
        tr.state = "loading"
        supplier = random.choice(SUPPLIERS)
        for area in range(1, 9):
            target = random.uniform(95, 140)
            n = 0.0
            if random.random() > 0.4:            # 40 %: same supplier spans into this area
                supplier = random.choice(SUPPLIERS)
            delivery = f"DLV-{ulid()}"
            seq = 0
            while n < target - 15:
                seq += 1
                n += await self.sack(supplier, delivery, seq, no, area, quick)
            if random.random() < 0.15:           # occasionally a second supplier tops it up
                other, odel = random.choice(SUPPLIERS), f"DLV-{ulid()}"
                for s in range(random.randint(1, 2)):
                    n += await self.sack(other, odel, s + 1, no, area, quick)
            self.area_n[(no, area)] = n

    async def sack(self, supplier, delivery, seq, trough, area, quick) -> float:
        async with self.lock_a:
            settings = self.c[A].settings
            tare = float(settings.get("default_sack_tare_kg", 1.0))
            net = round(random.uniform(22, 38), 1)
            wet = round(random.uniform(0.5, 2.0), 1) if random.random() < 0.10 else 0.0
            coarse = round(random.uniform(0.2, 1.0), 1) if random.random() < 0.05 else 0.0
            self.c[A].send("event", {
                "type": "sack_weighed", "supplier_id": supplier, "delivery_id": delivery, "sack_seq": seq,
                "gross_kg": round(net + tare + wet + coarse, 1), "sack_tare_kg": tare,
                "wet_deduction_kg": wet, "coarse_deduction_kg": coarse, "net_kg": net,
                "trough_no": trough, "area_no": area, "stable": True,
                "maturity": random.choice(["good", "good", "good", "fair", "coarse"]),
                "operator_id": OPERATORS[0]})
            self.counts["sacks"] += 1
            if quick:
                await asyncio.sleep(0.05)
            else:
                await self.psleep(random.uniform(30, 60))
        return net

    async def unload(self, no: int) -> None:
        b = self.c[B]
        for area in range(1, 9):
            n = self.area_n.pop((no, area), 0.0)
            remaining = n * (1 - random.uniform(0.42, 0.50))
            while remaining > 0.5:
                limit = float(b.settings.get("max_limit_kg", 25.0))
                if random.random() < 0.06:       # overfilled crate: rejected, lightened, re-weighed
                    over = round(limit * random.uniform(1.02, 1.08), 1)
                    b.send("event", self._crate(no, area, over, limit, over_limit=True))
                    self.counts["over_limit"] += 1
                    await self.psleep(40)
                net = round(min(remaining, limit * random.uniform(0.78, 0.97)), 1)
                if net < 0.5:
                    break
                b.send("event", self._crate(no, area, net, limit, over_limit=False))
                self.counts["crates"] += 1
                remaining -= net
                self.batch_wz += net
                if self.batch_wz >= self.batch_target:
                    asyncio.create_task(self.batch_flow(self.batch_id, self.batch_wz))
                    self.counts["batches"] += 1
                    self.batch_id, self.batch_wz = self._new_batch_id(), 0.0
                    self.batch_target = random.uniform(360, 440)
                await self.psleep(random.uniform(40, 70))
            b.send("event", {"type": "area_unloaded", "trough_no": no, "area_no": area,
                             "operator_id": OPERATORS[1]})

    def _crate(self, trough, area, net, limit, over_limit) -> dict:
        tare = 2.1
        return {"type": "crate_weighed", "trough_no": trough, "area_no": area,
                "crate_id": f"CR-{random.randint(1, 60):03d}", "gross_kg": round(net + tare, 1),
                "tare_kg": tare, "net_kg": net, "max_limit_kg": limit, "over_limit": over_limit,
                "stable": True, "batch_id": self.batch_id, "operator_id": OPERATORS[1]}

    # -- batch: rolling, fermentation, drying, D ------------------------------------

    async def batch_flow(self, batch_id: str, wz: float) -> None:
        w_prev = wz
        last = 3 if random.random() < 0.7 else 4
        for stage in range(1, last + 1):
            ratio = {1: (0.72, 0.78), 2: (0.70, 0.76), 3: (0.68, 0.74), 4: (0.72, 0.78)}[stage]
            total = w_prev * random.uniform(*ratio)
            duration = random.uniform(25, 35) * MIN
            until = time.time() + duration / self.speed
            for z in ROLLERS[stage]:
                self.plant.roller_busy_until[z] = max(self.plant.roller_busy_until.get(z, 0), until)
            await self.psleep(duration)
            left = total
            while left > 0.5:
                load = round(min(left, random.uniform(35, 50)), 1)
                self.c[W[stage]].send("event", {
                    "type": "stage_weighed", "batch_id": batch_id, "stage": stage, "net_kg": load,
                    "bulk": stage == last, "stable": True, "operator_id": OPERATORS[2 + stage]})
                left -= load
                await self.psleep(random.uniform(60, 120))
            w_prev = total
        self.plant.fermenting += 1
        await self.psleep(random.uniform(140, 160) * MIN)
        self.plant.fermenting -= 1
        dry = random.uniform(19, 23) * MIN
        self.plant.drier_loaded_until = max(self.plant.drier_loaded_until, time.time() + dry / self.speed)
        await self.psleep(dry)
        green = wz / random.uniform(0.52, 0.56)
        made = green * random.uniform(0.21, 0.23)
        async with self.lock_d:
            d = self.c[D]
            while made > 0.5:
                limit = float(d.settings.get("max_limit_kg", 30.0))
                load = round(min(made, limit * random.uniform(0.80, 0.95)), 1)
                body = {"type": "drier_output", "net_kg": load, "max_limit_kg": limit, "over_limit": False,
                        "moisture_pct": round(random.uniform(2.5, 3.5), 1), "stable": True,
                        "operator_id": OPERATORS[8]}
                # The backend's time-window assignment uses real minutes, so only
                # leave batch_id out when the clock runs at real speed.
                if self.speed > 1 or random.random() < 0.5:
                    body["batch_id"] = batch_id
                d.send("event", body)
                made -= load
                self.counts["made_tea_kg"] += load
                await self.psleep(random.uniform(60, 90))

    async def run(self) -> None:
        tasks = []
        for no in range(1, 12):
            # Start the troughs at different points of the wither.
            tasks.append(asyncio.create_task(self.trough_cycle(no, random.uniform(0.3, 0.95))))
        await asyncio.gather(*tasks)


class Faults:
    """Now and then push one zone past an alarm threshold long enough to trip
    its rule, or take a node off the air; plus duplicate messages."""

    def __init__(self, plant: Plant, clients: dict[str, DeviceClient]) -> None:
        self.plant, self.c = plant, clients

    async def run(self) -> None:
        asyncio.create_task(self.duplicates())
        await asyncio.sleep(random.uniform(60, 120))
        while True:
            kind = random.choice(["ferm_hot", "trough_hot", "fan_trip", "drier_hot", "node_outage"])
            now = time.time()
            if kind == "ferm_hot":
                spot = random.randint(1, 8)
                self.plant.ferm_hot_spot = (spot, now + 7 * 60)
                log.info("fault: fermentation spot IRS0%d hot for 7 min", spot)
            elif kind == "trough_hot":
                t = random.randint(1, 11)
                self.plant.troughs[t].hot_until = now + 7 * 60
                log.info("fault: trough %d air hot for 7 min", t)
            elif kind == "fan_trip":
                t = random.randint(1, 11)
                self.plant.troughs[t].fan_trip_until = now + 4 * 60
                log.info("fault: trough %d fan tripped for 4 min", t)
            elif kind == "drier_hot":
                self.plant.drier_hot_until = now + 4 * 60
                log.info("fault: drier inlet hot for 4 min")
            else:
                node = random.choice([d for d in self.c if "-NOD" in d])
                asyncio.create_task(self.outage(node, 150))
            await asyncio.sleep(random.uniform(4, 9) * 60)

    async def outage(self, device_id: str, seconds: float) -> None:
        log.info("fault: %s off the air for %ds (buffering)", device_id, seconds)
        self.c[device_id].paused = True
        await asyncio.sleep(seconds)
        self.c[device_id].paused = False
        log.info("fault: %s back, flushing %d buffered messages", device_id, self.c[device_id].outbox.qsize())

    async def duplicates(self) -> None:
        while True:
            await asyncio.sleep(random.uniform(60, 180))
            node = random.choice([d for d in self.c if "-NOD" in d])
            if not self.c[node].paused and await self.c[node].resend_duplicate():
                log.debug("re-sent a message from %s", node)
