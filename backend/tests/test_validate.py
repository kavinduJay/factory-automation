import pytest

from app.ingest import validate as v

PROFILE = {
    "id": "trough-node",
    "telemetry_schema": {
        "THS": {"t_c": {"min": -10, "max": 80}, "rh_pct": {"min": 0, "max": 100}},
        "CTS": {"amp": {"min": 0, "max": 100}, "run": {"type": "bool"}},
    },
}
SENSORS = {
    "TF01-U-TR03-THS01": {"device_id": "TF01-U-TR03-NOD01", "kind": "THS"},
    "TF01-U-TR03-CTS01": {"device_id": "TF01-U-TR03-NOD01", "kind": "CTS"},
    "TF01-U-TR04-THS01": {"device_id": "TF01-U-TR04-NOD01", "kind": "THS"},
}


def test_parse_topic():
    assert v.parse_topic("tf01/TF01-U-TR03-NOD01/telemetry", "tf01") == ("TF01-U-TR03-NOD01", "telemetry")
    assert v.parse_topic("tf01/X/rpc/res", "tf01") == ("X", "rpc/res")
    with pytest.raises(v.Invalid):
        v.parse_topic("other/X/telemetry", "tf01")
    with pytest.raises(v.Invalid):
        v.parse_topic("tf01/X/attributes/desired", "tf01")


def test_envelope():
    msg_id, ts = v.envelope({"msg_id": "01JC9X0000000000000000000A", "ts": "2026-11-05T08:15:00.000Z"})
    assert msg_id.startswith("01JC9X") and ts.tzinfo is not None and ts.hour == 8
    with pytest.raises(v.Invalid):
        v.envelope({"ts": "2026-11-05T08:15:00Z"})
    with pytest.raises(v.Invalid):
        v.envelope({"msg_id": "01JC9X0000000000000000000A", "ts": "yesterday"})


def test_readings_accept_and_reject():
    payload = {"readings": [
        {"sensor": "TF01-U-TR03-THS01", "t_c": 31.4, "rh_pct": 58.2},
        {"sensor": "TF01-U-TR03-CTS01", "amp": 9.8, "run": True},
        {"sensor": "TF01-U-TR03-THS01", "t_c": 120},          # out of range
        {"sensor": "TF01-U-TR03-THS01", "lux": 5},            # unknown key
        {"sensor": "TF01-U-TR04-THS01", "t_c": 30},           # other device's sensor
        {"sensor": "NOPE", "t_c": 30},
        {"sensor": "TF01-U-TR03-CTS01", "run": "yes"},        # not a bool
    ]}
    ok, bad = v.readings(payload, "TF01-U-TR03-NOD01", PROFILE, SENSORS)
    assert [(r.key, r.value) for r in ok] == [("t_c", 31.4), ("rh_pct", 58.2), ("amp", 9.8), ("run", 1.0)]
    assert len(bad) == 5


def test_event_validation():
    profile = {"id": "scale-bridge-w", "event_schema": {
        "stage_weighed": {"required": ["batch_id", "net_kg"], "numeric": ["net_kg"]}}}
    w2 = {"config": {"stage": 2}}
    ev = v.event({"type": "stage_weighed", "batch_id": "B1", "net_kg": 210.0, "stable": True}, profile, w2)
    assert ev["stage"] == 2
    with pytest.raises(v.Invalid, match="stable"):
        v.event({"type": "stage_weighed", "batch_id": "B1", "net_kg": 1.0, "stable": False}, profile, w2)
    with pytest.raises(v.Invalid, match="bulk"):
        v.event({"type": "stage_weighed", "batch_id": "B1", "net_kg": 1.0, "bulk": True}, profile, w2)
    with pytest.raises(v.Invalid, match="not allowed"):
        v.event({"type": "crate_weighed"}, profile, w2)
    with pytest.raises(v.Invalid, match="required"):
        v.event({"type": "stage_weighed", "net_kg": 1.0}, profile, w2)
