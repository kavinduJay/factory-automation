"""One long-lived MQTT connection for the backend, with reconnect.

Ingest consumes messages from it; the engine publishes settings through it.
"""
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import aiomqtt

from .config import settings

log = logging.getLogger(__name__)

SUBSCRIPTIONS = ("telemetry", "event", "attributes", "status", "rpc/res")


class MqttService:
    def __init__(self, on_message: Callable[[str, bytes, bool], Awaitable[None]],
                 on_connect: Callable[[], Awaitable[None]] | None = None) -> None:
        self.on_message = on_message
        self.on_connect = on_connect
        self._client: aiomqtt.Client | None = None
        self._connected = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host, port=settings.mqtt_port,
                    username=settings.mqtt_username, password=settings.mqtt_password,
                    identifier="tf01-backend", clean_session=False,
                ) as client:
                    self._client = client
                    for kind in SUBSCRIPTIONS:
                        await client.subscribe(f"{settings.site_prefix}/+/{kind}", qos=1)
                    self._connected.set()
                    backoff = 1
                    log.info("MQTT connected to %s:%s", settings.mqtt_host, settings.mqtt_port)
                    if self.on_connect:
                        asyncio.create_task(self.on_connect())
                    async for message in client.messages:
                        try:
                            await self.on_message(str(message.topic), message.payload, message.retain)
                        except Exception:
                            log.exception("error handling %s", message.topic)
            except aiomqtt.MqttError as e:
                log.warning("MQTT connection lost (%s); retrying in %ss", e, backoff)
            finally:
                self._connected.clear()
                self._client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def publish(self, topic: str, payload: dict | str, *, qos: int = 1,
                      retain: bool = False, timeout: float = 10) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout)
        data = payload if isinstance(payload, str) else json.dumps(payload)
        await self._client.publish(topic, data, qos=qos, retain=retain)
