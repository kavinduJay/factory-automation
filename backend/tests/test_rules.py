from datetime import datetime, timedelta, timezone

import pytest

from app.engine import rules as r

T0 = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
IRS = {"id": "TF01-L-FER-IRS01", "kind": "IRS", "position": "surface", "asset_id": "TF01-L-FER"}
DEV = {"id": "TF01-L-FER-NOD01", "profile_id": "fermentation-node"}
ANC = ["TF01-L-FER", "TF01-L", "TF01"]


def ferm_rule(**kw):
    row = {"id": 1, "name": "hot", "scope_asset_id": "TF01-L-FER", "scope_profile_id": None,
           "condition": {"sensor_kind": "IRS", "key": "t_c", "op": ">", "value": 30, "for_s": 300,
                         "hysteresis": 0.5},
           "action": {"alarm_type": "ferm_surface_high", "severity": "major"}}
    row["condition"].update(kw)
    return r.from_row(row)


def run(ev, values, step_s=60):
    out = []
    for i, v in enumerate(values):
        out += [(a.kind, i) for a in ev.evaluate(IRS, DEV, ANC, "t_c", v, T0 + timedelta(seconds=i * step_s))]
    return out


def test_raise_after_for_s_and_clear_with_hysteresis():
    ev = r.Evaluator([ferm_rule()])
    # above 30 from minute 1; 5 min later (minute 6) it raises
    values = [29, 31, 31, 31, 31, 31, 31, 30.8, 29.6, 29.4]
    assert run(ev, values) == [("raise", 6), ("clear", 9)]


def test_short_spike_does_not_alarm():
    ev = r.Evaluator([ferm_rule()])
    assert run(ev, [31, 31, 29, 31, 31, 31, 29]) == []


def test_scope_filters():
    rule = ferm_rule()
    assert rule.matches(IRS, DEV, ANC, "t_c")
    assert not rule.matches(IRS, DEV, ["TF01-U-TR01", "TF01-U", "TF01"], "t_c")
    assert not rule.matches({**IRS, "kind": "THH"}, DEV, ANC, "t_c")
    inlet = r.from_profile("drier-node", {"type": "x", "severity": "major", "sensor_kind": "TCK",
                                          "position": "inlet", "key": "t_c", "op": ">", "value": 125})
    tck = {"id": "s", "kind": "TCK", "position": "outlet"}
    assert not inlet.matches(tck, {"profile_id": "drier-node"}, [], "t_c")
    assert inlet.matches({**tck, "position": "inlet"}, {"profile_id": "drier-node"}, [], "t_c")
    assert not inlet.matches({**tck, "position": "inlet"}, {"profile_id": "other"}, [], "t_c")


def test_restart_keeps_open_alarm_state():
    ev = r.Evaluator([ferm_rule()], {("TF01-L-FER-IRS01", "ferm_surface_high")})
    assert run(ev, [31, 29]) == [("clear", 1)]


def test_invalid_rules():
    with pytest.raises(r.RuleError):
        ferm_rule(op="~")
    with pytest.raises(r.RuleError):
        r.from_row({"id": 2, "name": "x", "condition": {"sensor_kind": "IRS", "key": "t_c", "op": ">",
                                                         "value": 1}, "action": {"alarm_type": "a",
                                                                                 "severity": "low"}})
