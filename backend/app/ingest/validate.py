"""Pure validation of MQTT messages against device profiles. No I/O, so it is
unit-tested directly (tests/test_validate.py)."""
from dataclasses import dataclass
from datetime import datetime, timezone

TOPIC_KINDS = ("telemetry", "event", "attributes", "status", "rpc/res")
WEIGHING_EVENTS = ("sack_weighed", "crate_weighed", "stage_weighed", "drier_output")


class Invalid(ValueError):
    """Message (or one reading) fails validation; the reason is the message."""


@dataclass(frozen=True)
class Reading:
    sensor_id: str
    key: str
    value: float


def parse_topic(topic: str, prefix: str) -> tuple[str, str]:
    """'tf01/TF01-U-TR03-NOD01/telemetry' -> ('TF01-U-TR03-NOD01', 'telemetry')."""
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != prefix:
        raise Invalid(f"topic outside {prefix}/: {topic}")
    kind = "/".join(parts[2:])
    if kind not in TOPIC_KINDS:
        raise Invalid(f"unknown topic kind: {kind}")
    return parts[1], kind


def parse_ts(value) -> datetime:
    if not isinstance(value, str):
        raise Invalid("ts missing or not a string")
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        raise Invalid(f"ts not ISO 8601: {value}") from None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def envelope(payload) -> tuple[str, datetime]:
    """Every telemetry, event and attributes message carries msg_id and ts."""
    if not isinstance(payload, dict):
        raise Invalid("payload is not a JSON object")
    msg_id = payload.get("msg_id")
    if not isinstance(msg_id, str) or not 10 <= len(msg_id) <= 64:
        raise Invalid("msg_id missing or malformed")
    return msg_id, parse_ts(payload.get("ts"))


def _number(v, key: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Invalid(f"{key} is not a number")
    return float(v)


def readings(payload: dict, device_id: str, profile: dict, sensors: dict[str, dict]
             ) -> tuple[list[Reading], list[tuple[str, dict]]]:
    """Split a telemetry payload into accepted readings and (reason, item) rejects.

    Each item names a sensor that must belong to this device; every key must be
    in the profile's telemetry_schema for that sensor kind and within range.
    """
    items = payload.get("readings")
    if not isinstance(items, list):
        raise Invalid("readings missing or not a list")
    schema = profile.get("telemetry_schema") or {}
    ok: list[Reading] = []
    bad: list[tuple[str, dict]] = []
    for item in items:
        if not isinstance(item, dict):
            bad.append(("reading is not an object", {"item": item}))
            continue
        sid = item.get("sensor")
        sensor = sensors.get(sid)
        if sensor is None:
            bad.append((f"unknown sensor {sid}", item))
            continue
        if sensor["device_id"] != device_id:
            bad.append((f"sensor {sid} does not belong to {device_id}", item))
            continue
        kind_schema = schema.get(sensor["kind"])
        if kind_schema is None:
            bad.append((f"profile {profile['id']} has no telemetry for kind {sensor['kind']}", item))
            continue
        for key, raw in item.items():
            if key == "sensor":
                continue
            spec = kind_schema.get(key)
            if spec is None:
                bad.append((f"unknown key {key} for {sensor['kind']}", {"sensor": sid, key: raw}))
                continue
            try:
                if spec.get("type") == "bool":
                    if not isinstance(raw, bool):
                        raise Invalid(f"{key} is not a boolean")
                    value = 1.0 if raw else 0.0
                else:
                    value = _number(raw, key)
                    lo, hi = spec.get("min"), spec.get("max")
                    if (lo is not None and value < lo) or (hi is not None and value > hi):
                        raise Invalid(f"{key}={value} outside {lo}..{hi}")
            except Invalid as e:
                bad.append((str(e), {"sensor": sid, key: raw}))
                continue
            ok.append(Reading(sid, key, value))
    return ok, bad


def event(payload: dict, profile: dict, device: dict) -> dict:
    """Check an event against the profile's event_schema; returns the payload
    with defaults from the device config filled in (e.g. stage for W units)."""
    etype = payload.get("type")
    schema = (profile.get("event_schema") or {}).get(etype)
    if schema is None:
        raise Invalid(f"event type {etype!r} not allowed for profile {profile['id']}")
    out = dict(payload)
    if etype == "stage_weighed" and "stage" not in out:
        out["stage"] = (device.get("config") or {}).get("stage")
    for key in schema.get("required", []):
        if out.get(key) in (None, ""):
            raise Invalid(f"{etype}: {key} is required")
    for key in schema.get("numeric", []):
        if out.get(key) is not None:
            _number(out[key], key)
            if out[key] < 0:
                raise Invalid(f"{etype}: {key} is negative")
    for key, lo, hi in (("trough_no", 1, 11), ("area_no", 1, 8), ("stage", 1, 4)):
        if key in out and out[key] is not None:
            if isinstance(out[key], bool) or not isinstance(out[key], int) or not lo <= out[key] <= hi:
                raise Invalid(f"{etype}: {key} must be an integer {lo}..{hi}")
    if etype in WEIGHING_EVENTS and out.get("stable") is False:
        raise Invalid(f"{etype}: scale not stable; weight not accepted")
    if etype == "stage_weighed" and out.get("bulk") and not (device.get("config") or {}).get("can_mark_bulk"):
        raise Invalid("stage_weighed: only W3/W4 may mark bulk")
    return out
