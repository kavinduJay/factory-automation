"""FastAPI app. One process runs the three parts: ingest (MQTT -> DB), api
(REST + WebSocket) and engine (rules, offline detection, settings push)."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .alarms import AlarmService
from .config import settings
from .db import create_pool
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
    app.state.__dict__.update(pool=pool, registry=registry, hub=hub, alarms=alarms,
                              ingest=ingest, mqtt=mqtt)
    tasks = []
    if settings.run_background:
        tasks.append(asyncio.create_task(mqtt.run(), name="mqtt"))
    log.info("started: %d devices, %d sensors", len(registry.devices), len(registry.sensors))
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()


app = FastAPI(title="TF01 backend", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"ok": True, "mqtt": app.state.mqtt.connected}
