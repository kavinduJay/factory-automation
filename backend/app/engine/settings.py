"""Shared attributes (device settings): stored in `attribute` (scope shared),
pushed to the device as a retained message on tf01/{device_id}/attributes/desired
so a rebooted device gets them on connect. The device reports what it uses in
its client attribute `settings`; the dashboard compares the two."""
import logging

from ..db import dumps

log = logging.getLogger(__name__)


class SettingsError(ValueError):
    pass


def validate_changes(profile: dict, changes: dict) -> dict:
    """Only keys the profile defines, with the same type as the default."""
    defaults = profile.get("default_settings") or {}
    if not changes:
        raise SettingsError("no changes")
    out = {}
    for key, value in changes.items():
        if key not in defaults:
            raise SettingsError(f"{key} is not a setting of {profile['id']}")
        d = defaults[key]
        if isinstance(d, bool):
            if not isinstance(value, bool):
                raise SettingsError(f"{key} must be true or false")
        elif isinstance(d, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingsError(f"{key} must be a number")
            if value < 0:
                raise SettingsError(f"{key} must be >= 0")
            if key.endswith("_pct") and value > 100:
                raise SettingsError(f"{key} must be <= 100")
        elif isinstance(d, str) and not isinstance(value, str):
            raise SettingsError(f"{key} must be text")
        out[key] = value
    return out


class SettingsService:
    def __init__(self, pool, registry, mqtt, hub, prefix: str) -> None:
        self.pool, self.registry, self.mqtt, self.hub, self.prefix = pool, registry, mqtt, hub, prefix

    async def desired(self, device_id: str) -> dict:
        rows = await self.pool.fetch(
            "SELECT key, value FROM attribute WHERE entity_id = $1 AND scope = 'shared' ORDER BY key",
            device_id)
        return {r["key"]: r["value"] for r in rows}

    async def reported(self, device_id: str) -> dict | None:
        return await self.pool.fetchval(
            "SELECT value FROM attribute WHERE entity_id = $1 AND scope = 'client' AND key = 'settings'",
            device_id)

    async def state(self, device_id: str) -> dict:
        desired, reported = await self.desired(device_id), await self.reported(device_id)
        in_sync = reported is not None and all(reported.get(k) == v for k, v in desired.items())
        return {"device_id": device_id, "desired": desired, "reported": reported, "in_sync": in_sync}

    async def publish(self, device_id: str) -> None:
        await self.mqtt.publish(f"{self.prefix}/{device_id}/attributes/desired",
                                dumps(await self.desired(device_id)), qos=1, retain=True)

    async def publish_all(self) -> None:
        for device_id in self.registry.devices:
            try:
                await self.publish(device_id)
            except Exception:
                log.exception("publishing settings for %s", device_id)
        log.info("published desired settings for %d devices", len(self.registry.devices))

    async def update(self, device_id: str, changes: dict, username: str, reason: str | None) -> dict:
        profile = self.registry.profile_of(device_id)
        if profile is None:
            raise SettingsError(f"unknown device {device_id}")
        changes = validate_changes(profile, changes)
        old = await self.desired(device_id)
        async with self.pool.acquire() as c, c.transaction():
            await c.executemany(
                """INSERT INTO attribute (entity_id, scope, key, value, updated_at)
                   VALUES ($1, 'shared', $2, $3, now())
                   ON CONFLICT (entity_id, scope, key) DO UPDATE
                   SET value = EXCLUDED.value, updated_at = now()""",
                [(device_id, k, v) for k, v in changes.items()])
            await c.execute(
                """INSERT INTO audit_log (username, entity, action, old, new, reason)
                   VALUES ($1, $2, 'settings.update', $3, $4, $5)""",
                username, device_id, {k: old.get(k) for k in changes}, changes, reason)
        try:
            await self.publish(device_id)
        except Exception:
            # Stored; re-published to every device whenever MQTT reconnects.
            log.exception("settings for %s stored but not yet published", device_id)
        state = await self.state(device_id)
        await self.hub.broadcast({"type": "attributes", "device_id": device_id, "scope": "shared",
                                  "values": state["desired"]})
        return state
