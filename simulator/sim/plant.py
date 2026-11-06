"""Physical state of the factory and the readings it produces.

The process model (process.py) moves leaf and updates this state; the
telemetry loop samples it. Temperatures follow an upcountry Sri Lankan day
(about 17-26 °C outdoors) with noise; faults push a reading past an alarm
threshold for long enough to trip the rule, then recover.
"""
import math
import random
import time
from dataclasses import dataclass, field


def jitter(x: float, sd: float) -> float:
    return x + random.gauss(0, sd)


@dataclass
class Trough:
    no: int
    state: str = "empty"          # empty, loading, withering, waiting, unloading
    progress: float = 0.0         # wither progress 0..1
    fan_trip_until: float = 0.0
    hot_until: float = 0.0


@dataclass
class Plant:
    speed: float
    troughs: dict[int, Trough] = field(default_factory=lambda: {n: Trough(n) for n in range(1, 12)})
    roller_busy_until: dict[str, float] = field(default_factory=dict)   # zone -> real time
    fermenting: int = 0           # batches on the fermentation floor
    ferm_hot_spot: tuple[int, float] | None = None   # (IRS number, until)
    drier_loaded_until: float = 0.0
    drier_hot_until: float = 0.0
    start: float = field(default_factory=time.time)

    # -- environment -----------------------------------------------------------

    def process_hour(self) -> float:
        """Hour of day on the process clock (runs `speed` times real time),
        starting at 06:00 local."""
        return (6 + (time.time() - self.start) * self.speed / 3600) % 24

    def ambient(self) -> tuple[float, float]:
        h = self.process_hour()
        day = math.sin((h - 9) / 24 * 2 * math.pi)        # peak mid-afternoon
        t = 21.5 + 4.5 * day
        rh = 82 - 12 * day
        return jitter(t, 0.15), min(99.0, jitter(rh, 0.6))

    # -- per zone ---------------------------------------------------------------

    def trough(self, no: int, position: str) -> dict:
        tr = self.troughs[no]
        amb_t, amb_rh = self.ambient()
        fan_on = tr.state != "empty" and time.time() > tr.fan_trip_until
        if position == "fan":
            amp = jitter(10.2, 0.25) if fan_on else abs(jitter(0.05, 0.03))
            return {"amp": round(amp, 2), "run": fan_on}
        warm = 5.0 if fan_on and tr.state in ("loading", "withering") else 0.0
        if time.time() < tr.hot_until:
            warm += 12.0
        t = amb_t + warm
        if position == "plenum":
            rh = amb_rh - 10 if warm else amb_rh
        else:   # above the leaf: moist at the start of the wither, drier at the end
            t -= 1.2 if position == "near_end" else 1.8
            leaf_rh = 92 - 25 * tr.progress if tr.state != "empty" else amb_rh
            rh = (leaf_rh + amb_rh) / 2
        return {"t_c": round(jitter(t, 0.2), 2), "rh_pct": round(min(100.0, jitter(rh, 0.8)), 1)}

    def roller(self, zone: str, kind: str) -> dict:
        busy = time.time() < self.roller_busy_until.get(zone, 0)
        amb_t, amb_rh = self.ambient()
        if kind == "CTS":
            amp = jitter(21.0, 1.2) if busy else jitter(7.5, 0.3)
            return {"amp": round(amp, 2), "run": True}
        t = amb_t + (7.0 if busy else 1.5)
        return {"t_c": round(jitter(t, 0.25), 2), "rh_pct": round(min(100.0, jitter(amb_rh + 8, 1)), 1)}

    def fermentation(self, kind: str, n: int) -> dict:
        amb_t, _ = self.ambient()
        room = 24.5 + (amb_t - 21.5) * 0.25
        if kind == "THH":
            return {"t_c": round(jitter(room, 0.15), 2), "rh_pct": round(min(100.0, jitter(95, 0.8)), 1)}
        surface = room + (2.5 if self.fermenting else 0.3)
        hot = self.ferm_hot_spot
        if hot and hot[0] == n and time.time() < hot[1]:
            surface = 31.8
        return {"t_c": round(jitter(surface, 0.2), 2)}

    def drier(self, position: str) -> dict:
        loaded = time.time() < self.drier_loaded_until
        if position == "motor":
            return {"amp": round(jitter(12.5 if loaded else 9.0, 0.3), 2), "run": True}
        hot = time.time() < self.drier_hot_until
        base = {"inlet": 104.0, "outlet": 52.0, "exhaust": 47.0}[position]
        if hot:
            base += {"inlet": 26.0, "outlet": 9.0, "exhaust": 7.0}[position]
        if loaded and position != "inlet":
            base -= 3
        return {"t_c": round(jitter(base, 0.8), 1)}
