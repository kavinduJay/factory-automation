"""FastAPI app. One process runs the three parts: ingest (MQTT -> DB), api
(REST + WebSocket) and engine (rules, offline detection, settings push)."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .alarms import AlarmService
from .api import alarms as alarms_api, plant, records, users, ws
from .api.auth import bootstrap_admin
from .config import settings
from .db import create_pool
from .engine.engine import Engine
from .engine.settings import SettingsService
from .hub import Hub
from .ingest.service import Ingest
from .mqtt import MqttService
from .registry import Registry

logging.basicConfig(level=settings.log_level,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tf01")


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await create_pool(settings.database_url)
    registry = Registry()
    await registry.load(pool)
    hub = Hub()
    alarms = AlarmService(pool, hub)
    ingest = Ingest(pool, registry, alarms, hub, settings.site_prefix)
    mqtt = MqttService(ingest.handle)
    settings_svc = SettingsService(pool, registry, mqtt, hub, settings.site_prefix)
    # Re-publish every device's retained desired settings on each (re)connect.
    mqtt.on_connect = settings_svc.publish_all
    engine = Engine(pool, registry, alarms, ingest, settings.offline_check_s)
    await engine.load_rules()
    app.state.__dict__.update(pool=pool, registry=registry, hub=hub, alarms=alarms,
                              ingest=ingest, mqtt=mqtt, settings=settings_svc, engine=engine)
    if await bootstrap_admin(pool, settings.admin_username, settings.admin_password):
        log.info("created first user %r (role admin)", settings.admin_username)
    tasks = []
    if settings.run_background:
        tasks.append(asyncio.create_task(mqtt.run(), name="mqtt"))
        tasks.append(asyncio.create_task(engine.run(), name="engine"))
    log.info("started: %d devices, %d sensors", len(registry.devices), len(registry.sensors))
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()


app = FastAPI(title="TF01 backend", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
for module in (users, plant, records, alarms_api, ws):
    app.include_router(module.router)


@app.get("/api/health")
async def health():
    return {"ok": True, "mqtt": app.state.mqtt.connected}
