"""When-then alarm rules. Pure logic, no I/O (tests/test_rules.py).

A rule comes from a device profile's alarm_rules or from the rule table; both
compile to Rule. For each accepted reading the Evaluator tracks, per rule and
sensor, how long the condition has held:

  - raise once the condition has held continuously for for_s seconds
    (device time), so short spikes do not alarm;
  - clear once the value is back past the threshold by `hysteresis`.
"""
import operator
from dataclasses import dataclass
from datetime import datetime

OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le,
       "==": operator.eq, "!=": operator.ne}
SEVERITIES = ("critical", "major", "warning")


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    key: str                       # "profile:<id>:<type>" or "rule:<id>"
    alarm_type: str
    severity: str
    message: str
    sensor_kind: str
    reading_key: str
    op: str
    value: float
    for_s: float = 0
    hysteresis: float = 0
    position: str | None = None
    profile_id: str | None = None  # applies only to devices of this profile
    asset_id: str | None = None    # applies only to sensors under this asset
    rule_id: int | None = None

    def matches(self, sensor: dict, device: dict, ancestors: list[str], key: str) -> bool:
        return (sensor["kind"] == self.sensor_kind and key == self.reading_key
                and (self.position is None or sensor.get("position") == self.position)
                and (self.profile_id is None or device["profile_id"] == self.profile_id)
                and (self.asset_id is None or self.asset_id in ancestors))

    def holds(self, value: float) -> bool:
        return OPS[self.op](value, self.value)

    def cleared(self, value: float) -> bool:
        h = self.hysteresis
        if self.op in (">", ">="):
            return value < self.value - h if h else not self.holds(value)
        if self.op in ("<", "<="):
            return value > self.value + h if h else not self.holds(value)
        return not self.holds(value)


def check_condition(cond: dict) -> None:
    for k in ("sensor_kind", "key", "op", "value"):
        if k not in cond:
            raise RuleError(f"condition needs {k}")
    if cond["op"] not in OPS:
        raise RuleError(f"op must be one of {', '.join(OPS)}")
    for k in ("value", "for_s", "hysteresis"):
        if k in cond and (isinstance(cond[k], bool) or not isinstance(cond[k], (int, float))):
            raise RuleError(f"{k} must be a number")
    if cond.get("for_s", 0) < 0 or cond.get("hysteresis", 0) < 0:
        raise RuleError("for_s and hysteresis must be >= 0")


def check_action(action: dict) -> None:
    if not action.get("alarm_type"):
        raise RuleError("action needs alarm_type")
    if action.get("severity") not in SEVERITIES:
        raise RuleError(f"severity must be one of {', '.join(SEVERITIES)}")


def from_profile(profile_id: str, r: dict) -> Rule:
    check_condition(r)
    check_action({"alarm_type": r.get("type"), "severity": r.get("severity")})
    return Rule(key=f"profile:{profile_id}:{r['type']}", alarm_type=r["type"],
                severity=r["severity"], message=r.get("message", r["type"]),
                sensor_kind=r["sensor_kind"], reading_key=r["key"], op=r["op"],
                value=float(r["value"]), for_s=float(r.get("for_s", 0)),
                hysteresis=float(r.get("hysteresis", 0)), position=r.get("position"),
                profile_id=profile_id)


def from_row(row: dict) -> Rule:
    c, a = row["condition"], row["action"]
    check_condition(c)
    check_action(a)
    return Rule(key=f"rule:{row['id']}", alarm_type=a["alarm_type"], severity=a["severity"],
                message=a.get("message", row["name"]), sensor_kind=c["sensor_kind"],
                reading_key=c["key"], op=c["op"], value=float(c["value"]),
                for_s=float(c.get("for_s", 0)), hysteresis=float(c.get("hysteresis", 0)),
                position=c.get("position"), profile_id=row.get("scope_profile_id"),
                asset_id=row.get("scope_asset_id"), rule_id=row["id"])


@dataclass
class Action:
    kind: str          # "raise" or "clear"
    rule: Rule
    sensor_id: str
    value: float
    ts: datetime


class Evaluator:
    def __init__(self, rules: list[Rule], open_alarms: set[tuple[str, str]] = frozenset()) -> None:
        self.rules = rules
        self.open = set(open_alarms)                       # (entity_id, alarm_type)
        self.since: dict[tuple[str, str], datetime] = {}   # (rule.key, sensor_id) -> first true

    def evaluate(self, sensor: dict, device: dict, ancestors: list[str], key: str,
                 value: float, ts: datetime) -> list[Action]:
        out = []
        for rule in self.rules:
            if not rule.matches(sensor, device, ancestors, key):
                continue
            sid, state = sensor["id"], (rule.key, sensor["id"])
            active = (sid, rule.alarm_type) in self.open
            if not active:
                if rule.holds(value):
                    start = self.since.setdefault(state, ts)
                    if (ts - start).total_seconds() >= rule.for_s:
                        self.open.add((sid, rule.alarm_type))
                        self.since.pop(state, None)
                        out.append(Action("raise", rule, sid, value, ts))
                else:
                    self.since.pop(state, None)
            elif rule.cleared(value):
                self.open.discard((sid, rule.alarm_type))
                self.since.pop(state, None)
                out.append(Action("clear", rule, sid, value, ts))
        return out
