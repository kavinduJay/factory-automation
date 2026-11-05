"""One MQTT connection per simulated device, behaving like the firmware will:

- last-will `offline` (retained) on tf01/{id}/status, `online` on connect
- subscribes to its retained attributes/desired and applies the settings
- reports client attributes (fw, rssi, settings in use)
- every message has ts and a ULID msg_id; anything that cannot be sent is
  kept in an outbox and sent after reconnect, so an outage loses nothing
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timezone

import aiomqtt

from .devices import Device, default_settings
from .ulid import ulid

log = logging.getLogger(__name__)
FW = "sim-0.1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class DeviceClient:
    def __init__(self, device: Device, host: str, port: int, prefix: str) -> None:
        self.d = device
        self.host, self.port, self.prefix = host, port, prefix
        self.settings = default_settings(device)
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.connected = asyncio.Event()
        self.paused = False            # simulated outage: buffer instead of sending
        self.sent: list[tuple[str, str]] = []   # recent (topic, body), for duplicate injection
        self._client: aiomqtt.Client | None = None

    def topic(self, kind: str) -> str:
        return f"{self.prefix}/{self.d.id}/{kind}"

    def envelope(self, body: dict) -> dict:
        return {"msg_id": ulid(), "ts": now_iso(), **body}

    def send(self, kind: str, body: dict) -> dict:
        msg = self.envelope(body)
        self.outbox.put_nowait((self.topic(kind), json.dumps(msg), 0 if kind == "telemetry" else 1))
        return msg

    def report_attributes(self) -> None:
        self.send("attributes", {"fw": FW, "rssi": random.randint(-75, -48),
                                 "settings": self.settings, "buffered": self.outbox.qsize()})

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                will = aiomqtt.Will(self.topic("status"), "offline", qos=1, retain=True)
                async with aiomqtt.Client(self.host, self.port, identifier=f"sim-{self.d.id}",
                                          username=self.d.id, will=will, keepalive=30) as c:
                    self._client = c
                    await c.publish(self.topic("status"), "online", qos=1, retain=True)
                    await c.subscribe(self.topic("attributes/desired"), qos=1)
                    self.connected.set()
                    backoff = 1
                    self.report_attributes()
                    sender = asyncio.create_task(self._sender(c))
                    try:
                        async for m in c.messages:
                            self._apply_desired(m.payload)
                    finally:
                        sender.cancel()
            except aiomqtt.MqttError as e:
                log.warning("%s: MQTT %s; retry in %ss", self.d.id, e, backoff)
            finally:
                self.connected.clear()
                self._client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _sender(self, c: aiomqtt.Client) -> None:
        while True:
            while self.paused:
                await asyncio.sleep(1)
            topic, body, qos = await self.outbox.get()
            try:
                await c.publish(topic, body, qos=qos)
            except aiomqtt.MqttError:
                # put it back at the front: rebuild the queue
                rest = [(topic, body, qos)]
                while not self.outbox.empty():
                    rest.append(self.outbox.get_nowait())
                for item in rest:
                    self.outbox.put_nowait(item)
                raise
            if topic.endswith("/telemetry"):
                self.sent = (self.sent + [(topic, body)])[-20:]

    def _apply_desired(self, payload: bytes) -> None:
        try:
            desired = json.loads(payload)
        except ValueError:
            log.warning("%s: bad desired payload", self.d.id)
            return
        if not isinstance(desired, dict):
            return
        changed = {k: v for k, v in desired.items() if self.settings.get(k) != v}
        self.settings.update(desired)
        if changed:
            log.info("%s: applied settings %s", self.d.id, changed)
        self.report_attributes()

    async def resend_duplicate(self) -> bool:
        """Re-publish an already sent message with the same msg_id, as a
        bridge does when it is unsure the broker got it."""
        if not self.sent or self._client is None:
            return False
        topic, body = random.choice(self.sent)
        await self._client.publish(topic, body, qos=0)
        return True
