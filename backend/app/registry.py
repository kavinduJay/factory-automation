"""In-memory copy of the asset tree, profiles, devices and sensors.

Loaded at startup and reloaded when profiles or rules change. Ingest and the
rule engine read it on every message, so it avoids a query per reading.
"""
from dataclasses import dataclass, field

import asyncpg


@dataclass
class Registry:
    profiles: dict[str, dict] = field(default_factory=dict)
    devices: dict[str, dict] = field(default_factory=dict)
    sensors: dict[str, dict] = field(default_factory=dict)
    assets: dict[str, dict] = field(default_factory=dict)

    async def load(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as c:
            self.profiles = {r["id"]: dict(r) for r in await c.fetch("SELECT * FROM device_profile")}
            self.devices = {r["id"]: dict(r) for r in await c.fetch(
                "SELECT id, profile_id, asset_id, name, point, config, online, last_seen FROM device")}
            self.sensors = {r["id"]: dict(r) for r in await c.fetch("SELECT * FROM sensor")}
            self.assets = {r["id"]: dict(r) for r in await c.fetch("SELECT * FROM asset")}

    def ancestors(self, asset_id: str) -> list[str]:
        """The asset and all its parents, nearest first."""
        out = []
        while asset_id and asset_id in self.assets and asset_id not in out:
            out.append(asset_id)
            asset_id = self.assets[asset_id]["parent_id"]
        return out

    def profile_of(self, device_id: str) -> dict | None:
        d = self.devices.get(device_id)
        return self.profiles.get(d["profile_id"]) if d else None
