"""Rule engine, offline detection and housekeeping."""
import asyncio
import logging
from datetime import datetime, timezone

from ..ingest.validate import Reading
from . import rules as r

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, pool, registry, alarms, ingest, check_s: float = 15) -> None:
        self.pool, self.registry, self.alarms, self.ingest = pool, registry, alarms, ingest
        self.check_s = check_s
        self.evaluator = r.Evaluator([])
        ingest.readings_listeners.append(self.on_readings)

    async def load_rules(self) -> int:
        """(Re)build rules from profiles and the rule table; keeps which
        alarms are open so a restart can still clear them."""
        compiled: list[r.Rule] = []
        for pid, profile in self.registry.profiles.items():
            for item in profile.get("alarm_rules") or []:
                try:
                    compiled.append(r.from_profile(pid, item))
                except r.RuleError as e:
                    log.error("profile %s rule %s skipped: %s", pid, item.get("type"), e)
        for row in await self.pool.fetch("SELECT * FROM rule WHERE enabled ORDER BY id"):
            try:
                compiled.append(r.from_row(dict(row)))
            except r.RuleError as e:
                log.error("rule %s skipped: %s", row["id"], e)
        open_alarms = {(a["entity_id"], a["type"]) for a in await self.alarms.open_alarms()}
        old_since = self.evaluator.since
        self.evaluator = r.Evaluator(compiled, open_alarms)
        self.evaluator.since = {k: v for k, v in old_since.items()
                                if any(k[0] == rule.key for rule in compiled)}
        log.info("loaded %d alarm rules", len(compiled))
        return len(compiled)

    async def on_readings(self, device_id: str, ts: datetime, readings: list[Reading]) -> None:
        device = self.registry.devices[device_id]
        for reading in readings:
            sensor = self.registry.sensors[reading.sensor_id]
            ancestors = self.registry.ancestors(sensor["asset_id"])
            for action in self.evaluator.evaluate(sensor, device, ancestors, reading.key,
                                                  reading.value, ts):
                rule = action.rule
                if action.kind == "raise":
                    await self.alarms.raise_(
                        entity_id=action.sensor_id, device_id=device_id, type=rule.alarm_type,
                        severity=rule.severity, message=f"{sensor['name']}: {rule.message}",
                        rule_id=rule.rule_id, ts=ts,
                        details={"value": action.value, "key": rule.reading_key, "op": rule.op,
                                 "threshold": rule.value, "for_s": rule.for_s, "rule": rule.key})
                else:
                    await self.alarms.clear(entity_id=action.sensor_id, type=rule.alarm_type, ts=ts)

    async def check_offline(self) -> list[str]:
        now = datetime.now(timezone.utc)
        went = []
        for device_id, dev in self.registry.devices.items():
            if not dev.get("online") or dev.get("last_seen") is None:
                continue
            limit = self.registry.profile_of(device_id)["offline_after_s"]
            silent = (now - dev["last_seen"]).total_seconds()
            if silent > limit:
                await self.ingest.set_online(device_id, False, f"no data for {int(silent)} s")
                went.append(device_id)
        return went

    async def run(self) -> None:
        last_prune = 0.0
        while True:
            try:
                await self.check_offline()
                loop_t = asyncio.get_running_loop().time()
                if loop_t - last_prune > 3600:
                    n = await self.ingest.prune()
                    last_prune = loop_t
                    if n:
                        log.info("pruned %d old msg_ids", n)
            except Exception:
                log.exception("engine loop")
            await asyncio.sleep(self.check_s)
