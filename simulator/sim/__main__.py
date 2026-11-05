"""Simulated TF01 devices. Environment: MQTT_HOST, MQTT_PORT, SITE_PREFIX,
SIM_SPEED (process clock multiplier), SIM_FAULTS (1/0), LOG_LEVEL."""
import asyncio
import logging
import os

from .client import DeviceClient
from .devices import build
from .plant import Plant
from .process import Faults, Process

log = logging.getLogger("sim")


def readings(plant: Plant, device) -> list[dict]:
    out = []
    for s in device.sensors:
        if device.kind == "trough":
            values = plant.trough(device.trough_no, s.position)
        elif device.kind == "rolling":
            values = plant.roller(s.zone, s.kind)
        elif device.kind == "fermentation":
            values = plant.fermentation(s.kind, int(s.id[-2:]))
        elif device.kind == "drier":
            values = plant.drier(s.position)
        else:
            t, rh = plant.ambient()
            values = {"t_c": round(t, 2), "rh_pct": round(rh, 1)}
        out.append({"sensor": s.id, **values})
    return out


async def telemetry_loop(plant: Plant, client: DeviceClient) -> None:
    await client.connected.wait()
    while True:
        client.send("telemetry", {"readings": readings(plant, client.d)})
        await asyncio.sleep(max(1.0, float(client.settings.get("poll_s", 10))))


async def heartbeat_loop(client: DeviceClient) -> None:
    await client.connected.wait()
    while True:
        await asyncio.sleep(60)
        client.report_attributes()


async def summary_loop(process: Process, clients: dict[str, DeviceClient]) -> None:
    while True:
        await asyncio.sleep(60)
        buffered = sum(c.outbox.qsize() for c in clients.values())
        states = "".join(t.state[0].upper() for t in process.plant.troughs.values())
        log.info("sim: %s | troughs %s | buffered %d", process.counts, states, buffered)


async def main() -> None:
    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    prefix = os.environ.get("SITE_PREFIX", "tf01")
    speed = float(os.environ.get("SIM_SPEED", "60"))
    faults = os.environ.get("SIM_FAULTS", "1") == "1"

    devices = build()
    clients = {d.id: DeviceClient(d, host, port, prefix) for d in devices.values()}
    plant = Plant(speed=speed)
    process = Process(plant, clients, speed)
    log.info("simulating %d devices at %gx, faults %s", len(clients), speed, "on" if faults else "off")

    tasks = [asyncio.create_task(c.run()) for c in clients.values()]
    await asyncio.wait_for(asyncio.gather(*(c.connected.wait() for c in clients.values())), timeout=120)
    # Give each device a moment to receive its retained settings first.
    await asyncio.sleep(2)
    for c in clients.values():
        if c.d.kind == "bridge":
            tasks.append(asyncio.create_task(heartbeat_loop(c)))
        else:
            tasks.append(asyncio.create_task(telemetry_loop(plant, c)))
    tasks.append(asyncio.create_task(process.run()))
    tasks.append(asyncio.create_task(summary_loop(process, clients)))
    if faults:
        tasks.append(asyncio.create_task(Faults(plant, clients).run()))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
