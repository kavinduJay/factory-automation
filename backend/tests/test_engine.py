import json
from datetime import datetime, timedelta, timezone

import pytest

from app.engine.engine import Engine
from app.engine.settings import SettingsError, SettingsService

T0 = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
_n = 0


def tel(sensor, ts, **values) -> bytes:
    global _n
    _n += 1
    return json.dumps({"msg_id": f"01ENGINE{_n:018d}", "ts": ts.isoformat(),
                       "readings": [{"sensor": sensor, **values}]}).encode()


class FakeMqtt:
    def __init__(self):
        self.published = []

    async def publish(self, topic, payload, qos=1, retain=False):
        self.published.append((topic, json.loads(payload), retain))


async def test_fermentation_rule_raises_and_clears(stack):
    engine = Engine(stack.pool, stack.registry, stack.alarms, stack.ingest)
    assert await engine.load_rules() >= 1
    s, topic = "TF01-L-FER-IRS02", "tf01/TF01-L-FER-NOD01/telemetry"
    for i, v in enumerate([31, 31, 31, 31, 31, 31]):
        await stack.ingest.handle(topic, tel(s, T0 + timedelta(minutes=i), t_c=v))
    a = await stack.pool.fetchrow("SELECT * FROM alarm WHERE entity_id = $1", s)
    assert a["type"] == "ferm_surface_high" and a["severity"] == "major" and a["rule_id"] == 1
    assert a["status"] == "active"
    await stack.ingest.handle(topic, tel(s, T0 + timedelta(minutes=7), t_c=29))
    assert await stack.pool.fetchval("SELECT status FROM alarm WHERE id = $1", a["id"]) == "cleared"


async def test_profile_rule_on_fan(stack):
    engine = Engine(stack.pool, stack.registry, stack.alarms, stack.ingest)
    await engine.load_rules()
    s, topic = "TF01-U-TR05-CTS01", "tf01/TF01-U-TR05-NOD01/telemetry"
    for i in range(4):  # fan_stopped: amp < 1 for 120 s
        await stack.ingest.handle(topic, tel(s, T0 + timedelta(minutes=i), amp=0.1, run=False))
    assert await stack.pool.fetchval(
        "SELECT severity FROM alarm WHERE entity_id = $1 AND type = 'fan_stopped'", s) == "warning"


async def test_offline_detection(stack):
    engine = Engine(stack.pool, stack.registry, stack.alarms, stack.ingest)
    node = "TF01-G-ENV-NOD01"
    await stack.ingest.handle(f"tf01/{node}/telemetry", tel("TF01-G-ENV-THS01", T0, t_c=25))
    assert await engine.check_offline() == []
    stack.registry.devices[node]["last_seen"] -= timedelta(seconds=600)
    assert await engine.check_offline() == [node]
    assert await stack.pool.fetchval(
        "SELECT status FROM alarm WHERE entity_id = $1 AND type = 'offline'", node) == "active"
    await stack.ingest.handle(f"tf01/{node}/telemetry", tel("TF01-G-ENV-THS01", T0, t_c=25))
    assert await stack.pool.fetchval(
        "SELECT status FROM alarm WHERE entity_id = $1 AND type = 'offline'", node) == "cleared"


async def test_settings_update_publishes_retained_and_audits(stack):
    mqtt = FakeMqtt()
    svc = SettingsService(stack.pool, stack.registry, mqtt, stack.hub, "tf01")
    b = "TF01-U-WWB-SCB01"
    state = await svc.update(b, {"max_limit_kg": 24.0}, "kavindu", "lighter crates")
    assert state["desired"]["max_limit_kg"] == 24.0 and not state["in_sync"]
    topic, payload, retain = mqtt.published[-1]
    assert topic == f"tf01/{b}/attributes/desired" and retain
    assert payload == {"max_limit_kg": 24.0, "amber_pct": 5, "min_weight_kg": 0.5,
                       "stability_band_kg": 0.05}
    audit = await stack.pool.fetchrow("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1")
    assert audit["old"] == {"max_limit_kg": 25.0} and audit["new"] == {"max_limit_kg": 24.0}
    # Device reports it applied the settings.
    await stack.ingest.handle(f"tf01/{b}/attributes", json.dumps(
        {"msg_id": "01SETTINGS000000000000001", "ts": T0.isoformat(), "settings": payload}).encode())
    assert (await svc.state(b))["in_sync"]
    with pytest.raises(SettingsError):
        await svc.update(b, {"colour": "red"}, "kavindu", None)
    with pytest.raises(SettingsError):
        await svc.update(b, {"amber_pct": 500}, "kavindu", None)
