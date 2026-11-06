"""The 25 devices and their sensors, per docs/DEVICES.md. Kept in code (not
read from the database) because a real device only knows its own config."""
from dataclasses import dataclass, field


@dataclass
class Sensor:
    id: str
    kind: str
    position: str
    zone: str        # e.g. TR03, RC1, FER


@dataclass
class Device:
    id: str
    kind: str        # trough, rolling, fermentation, drier, ambient, bridge
    point: str | None = None
    sensors: list[Sensor] = field(default_factory=list)
    trough_no: int | None = None


def build() -> dict[str, Device]:
    devs: dict[str, Device] = {}
    for t in range(1, 12):
        z = f"TR{t:02d}"
        d = Device(f"TF01-U-{z}-NOD01", "trough", trough_no=t)
        for n, pos in ((1, "plenum"), (2, "near_end"), (3, "far_end")):
            d.sensors.append(Sensor(f"TF01-U-{z}-THS0{n}", "THS", pos, z))
        d.sensors.append(Sensor(f"TF01-U-{z}-CTS01", "CTS", "fan", z))
        devs[d.id] = d
    for node, zones in (("NOD01", ("RC1", "RC2", "RC3")), ("NOD02", ("R21", "R22", "R23")),
                        ("NOD03", ("R31", "R32", "R41"))):
        d = Device(f"TF01-L-ROL-{node}", "rolling")
        for z in zones:
            d.sensors.append(Sensor(f"TF01-L-{z}-THS01", "THS", "leaf", z))
            d.sensors.append(Sensor(f"TF01-L-{z}-CTS01", "CTS", "motor", z))
        devs[d.id] = d
    f1 = Device("TF01-L-FER-NOD01", "fermentation")
    f1.sensors += [Sensor(f"TF01-L-FER-THH0{n}", "THH", "room", "FER") for n in (1, 2, 3)]
    f1.sensors += [Sensor(f"TF01-L-FER-IRS0{n}", "IRS", "surface", "FER") for n in (1, 2, 3, 4)]
    f2 = Device("TF01-L-FER-NOD02", "fermentation")
    f2.sensors += [Sensor(f"TF01-L-FER-IRS0{n}", "IRS", "surface", "FER") for n in (5, 6, 7, 8)]
    dry = Device("TF01-L-DRY-NOD01", "drier")
    dry.sensors += [Sensor("TF01-L-DRY-TCK01", "TCK", "inlet", "DRY"),
                    Sensor("TF01-L-DRY-TCK02", "TCK", "outlet", "DRY"),
                    Sensor("TF01-L-DRY-TCK03", "TCK", "exhaust", "DRY"),
                    Sensor("TF01-L-DRY-CTS01", "CTS", "motor", "DRY")]
    env = Device("TF01-G-ENV-NOD01", "ambient", sensors=[Sensor("TF01-G-ENV-THS01", "THS", "outdoor", "ENV")])
    for d in (f1, f2, dry, env):
        devs[d.id] = d
    for did, point in (("TF01-U-RCV-SCB01", "A"), ("TF01-U-WWB-SCB01", "B"),
                       ("TF01-L-RW1-SCB01", "W1"), ("TF01-L-RW2-SCB01", "W2"),
                       ("TF01-L-RW3-SCB01", "W3"), ("TF01-L-RW4-SCB01", "W4"),
                       ("TF01-L-DRO-SCB01", "D")):
        devs[did] = Device(did, "bridge", point=point)
    return devs


DEFAULT_SETTINGS = {
    "trough": {"poll_s": 10}, "rolling": {"poll_s": 10}, "fermentation": {"poll_s": 10},
    "drier": {"poll_s": 10}, "ambient": {"poll_s": 30},
    "A": {"min_weight_kg": 0.5, "stability_band_kg": 0.05, "default_sack_tare_kg": 1.0},
    "B": {"max_limit_kg": 25.0, "amber_pct": 5, "min_weight_kg": 0.5, "stability_band_kg": 0.05},
    "W": {"min_weight_kg": 0.5, "stability_band_kg": 0.05},
    "D": {"max_limit_kg": 30.0, "amber_pct": 5, "min_weight_kg": 0.5, "stability_band_kg": 0.05},
}


def default_settings(d: Device) -> dict:
    if d.kind != "bridge":
        return dict(DEFAULT_SETTINGS[d.kind])
    return dict(DEFAULT_SETTINGS["W" if d.point.startswith("W") else d.point])
