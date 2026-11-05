import json

import httpx
import pytest

from app.api.auth import bootstrap_admin, hash_password, make_token, read_token, verify_password
from app.engine.engine import Engine
from app.engine.settings import SettingsService
from app.main import app

from .test_engine import FakeMqtt


@pytest.fixture
async def client(stack):
    mqtt = FakeMqtt()
    mqtt.connected = True
    engine = Engine(stack.pool, stack.registry, stack.alarms, stack.ingest)
    await engine.load_rules()
    app.state.__dict__.update(pool=stack.pool, registry=stack.registry, hub=stack.hub, alarms=stack.alarms,
                              ingest=stack.ingest, mqtt=mqtt, engine=engine,
                              settings=SettingsService(stack.pool, stack.registry, mqtt, stack.hub, "tf01"))
    await bootstrap_admin(stack.pool, "admin", "admin-pass-1")
    await stack.pool.execute(
        "INSERT INTO app_user (username, password_hash, role) VALUES ('op', $1, 'operator')",
        hash_password("operator-pass"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.stack, c.mqtt = stack, mqtt
        yield c


async def login(c, user="admin", pw="admin-pass-1"):
    r = await c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_password_and_token():
    h = hash_password("secret-123")
    assert verify_password("secret-123", h) and not verify_password("nope", h)
    assert read_token(make_token("kavindu")) == "kavindu"
    assert read_token(make_token("kavindu") + "x") is None
    assert read_token(make_token("kavindu", ttl_s=-1)) is None


async def test_login_required_and_roles(client):
    assert (await client.get("/api/live")).status_code == 401
    assert (await client.post("/api/auth/login", json={"username": "admin", "password": "x"})).status_code == 401
    op = await login(client, "op", "operator-pass")
    assert (await client.get("/api/live", headers=op)).status_code == 200
    r = await client.put("/api/devices/TF01-U-WWB-SCB01/settings", headers=op, json={"changes": {"max_limit_kg": 20}})
    assert r.status_code == 403
    assert (await client.get("/api/users", headers=op)).status_code == 403


async def test_live_and_history(client):
    h = await login(client)
    await client.stack.ingest.handle("tf01/TF01-U-TR01-NOD01/telemetry", json.dumps({
        "msg_id": "01APITEST0000000000000001", "ts": "2026-11-05T08:00:00Z",
        "readings": [{"sensor": "TF01-U-TR01-THS01", "t_c": 30.5, "rh_pct": 60}]}).encode())
    live = (await client.get("/api/live", headers=h)).json()
    assert len(live["devices"]) == 25
    assert live["readings"]["TF01-U-TR01-THS01"]["t_c"]["value"] == 30.5
    assert live["settings"]["TF01-U-WWB-SCB01"]["desired"]["max_limit_kg"] == 25.0
    r = await client.get("/api/history", headers=h, params={
        "sensor_id": "TF01-U-TR01-THS01", "key": "t_c", "from": "2026-11-05T07:00:00Z",
        "to": "2026-11-05T09:00:00Z"})
    assert r.json()["series"][0]["points"][0][1] == 30.5
    r = await client.get("/api/history", headers=h, params={
        "sensor_id": "TF01-U-TR01-THS01", "from": "2026-11-05T00:00:00Z", "to": "2026-11-06T00:00:00Z"})
    series = {x["key"]: x for x in r.json()["series"]}
    assert r.json()["resolution"] == "1m" and series["t_c"]["points"][0][1] == 30.5
    assert series["rh_pct"]["points"][0][1] == 60


async def test_settings_put_publishes(client):
    h = await login(client)
    r = await client.put("/api/devices/TF01-U-WWB-SCB01/settings", headers=h,
                         json={"changes": {"max_limit_kg": 23.5}, "reason": "test"})
    assert r.status_code == 200 and r.json()["desired"]["max_limit_kg"] == 23.5
    assert client.mqtt.published[-1][0] == "tf01/TF01-U-WWB-SCB01/attributes/desired"
    r = await client.put("/api/devices/TF01-U-WWB-SCB01/settings", headers=h, json={"changes": {"x": 1}})
    assert r.status_code == 422


async def test_correction_endpoint(client):
    h = await login(client)
    await client.stack.ingest.handle("tf01/TF01-U-WWB-SCB01/event", json.dumps({
        "msg_id": "01APITEST0000000000000002", "ts": "2026-11-05T08:00:00Z", "type": "crate_weighed",
        "trough_no": 2, "area_no": 3, "net_kg": 20.0, "stable": True, "batch_id": "B5"}).encode())
    crate = (await client.get("/api/weighings/crate", headers=h)).json()[0]
    r = await client.post(f"/api/weighings/crate/{crate['id']}/correct", headers=h,
                          json={"changes": {"net_kg": 21.5}, "reason": "scale misread"})
    assert r.status_code == 201 and r.json()["corrects_id"] == crate["id"]
    # correcting the correction still points at the original
    r2 = await client.post(f"/api/weighings/crate/{r.json()['id']}/correct", headers=h,
                           json={"changes": {"net_kg": 21.0}, "reason": "second look"})
    assert r2.json()["corrects_id"] == crate["id"]
    eff = (await client.get("/api/weighings/crate", headers=h)).json()
    assert len(eff) == 1 and eff[0]["net_kg"] == 21.0 and eff[0]["original_id"] == crate["id"]
    assert len((await client.get("/api/weighings/crate", headers=h, params={"history": True})).json()) == 3
    r = await client.post(f"/api/weighings/crate/{crate['id']}/correct", headers=h,
                          json={"changes": {"trough_no": 4}, "reason": "nope"})
    assert r.status_code == 422
    r = await client.post(f"/api/weighings/crate/{crate['id']}/correct", headers=h,
                          json={"voided": True, "reason": "test crate"})
    assert (await client.get("/api/weighings/crate", headers=h)).json() == []
    assert (await client.get("/api/batches/B5", headers=h)).json()["wz_kg"] == 0


async def test_alarm_ack_and_rules(client):
    h = await login(client)
    op = await login(client, "op", "operator-pass")
    await client.stack.ingest.handle("tf01/TF01-G-ENV-NOD01/status", b"offline")
    await client.stack.ingest.set_online("TF01-G-ENV-NOD01", True, "x")
    await client.stack.ingest.set_online("TF01-G-ENV-NOD01", False, "x")
    alarms = (await client.get("/api/alarms", headers=op)).json()
    assert alarms[0]["type"] == "offline"
    r = await client.post(f"/api/alarms/{alarms[0]['id']}/ack", headers=op)
    assert r.json()["status"] == "acked" and r.json()["acked_by"] == "op"
    r = await client.post("/api/rules", headers=h, json={
        "name": "Outdoor hot", "scope_asset_id": "TF01-G-ENV",
        "condition": {"sensor_kind": "THS", "key": "t_c", "op": ">", "value": 33, "for_s": 0},
        "action": {"alarm_type": "outdoor_hot", "severity": "warning"}})
    assert r.status_code == 201
    await client.stack.ingest.handle("tf01/TF01-G-ENV-NOD01/telemetry", json.dumps({
        "msg_id": "01APITEST0000000000000003", "ts": "2026-11-05T08:00:00Z",
        "readings": [{"sensor": "TF01-G-ENV-THS01", "t_c": 34}]}).encode())
    assert any(a["type"] == "outdoor_hot" for a in (await client.get("/api/alarms", headers=h)).json())
    assert (await client.delete(f"/api/rules/{r.json()['id']}", headers=h)).status_code == 204
    assert not any(a["type"] == "outdoor_hot" for a in (await client.get("/api/alarms", headers=h)).json())
    r = await client.post("/api/rules", headers=h, json={
        "name": "bad", "condition": {"sensor_kind": "THS", "key": "t_c", "op": "?", "value": 1},
        "action": {"alarm_type": "x", "severity": "major"}})
    assert r.status_code == 422


async def test_users(client):
    h = await login(client)
    r = await client.post("/api/users", headers=h, json={"username": "manager1", "password": "manager-pass",
                                                         "role": "manager"})
    assert r.status_code == 201
    m = await login(client, "manager1", "manager-pass")
    assert (await client.get("/api/auth/me", headers=m)).json()["role"] == "manager"
    await client.patch(f"/api/users/{r.json()['id']}", headers=h, json={"active": False})
    assert (await client.get("/api/auth/me", headers=m)).status_code == 401
