"""Alarms, rules and the audit log."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..db import records
from ..engine import rules as r
from .auth import CONFIGURE, current_user, require

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


class RuleBody(BaseModel):
    name: str
    scope_asset_id: str | None = None
    scope_profile_id: str | None = None
    condition: dict
    action: dict
    enabled: bool = True


@router.get("/alarms")
async def alarms(request: Request, status: str = Query("open", pattern="^(open|all|cleared)$"),
                 entity_id: str | None = None, limit: int = Query(200, le=5000)):
    cond = {"open": "cleared_at IS NULL", "cleared": "cleared_at IS NOT NULL", "all": "true"}[status]
    return records(await request.app.state.pool.fetch(
        f"""SELECT * FROM alarm WHERE {cond} AND ($1::text IS NULL OR entity_id = $1)
            ORDER BY started_at DESC LIMIT $2""", entity_id, limit))


@router.post("/alarms/{alarm_id}/ack")
async def ack(alarm_id: int, request: Request, user: dict = Depends(current_user)):
    alarm = await request.app.state.alarms.ack(alarm_id, user["username"])
    if alarm is None:
        raise HTTPException(404, "no such alarm, or already acknowledged")
    return alarm


async def _check(request: Request, body: RuleBody) -> None:
    reg = request.app.state.registry
    try:
        r.check_condition(body.condition)
        r.check_action(body.action)
    except r.RuleError as e:
        raise HTTPException(422, str(e)) from None
    if body.scope_asset_id and body.scope_asset_id not in reg.assets:
        raise HTTPException(422, "no such asset")
    if body.scope_profile_id and body.scope_profile_id not in reg.profiles:
        raise HTTPException(422, "no such profile")


@router.get("/rules")
async def rules(request: Request):
    return records(await request.app.state.pool.fetch("SELECT * FROM rule ORDER BY id"))


@router.post("/rules", status_code=201)
async def create_rule(body: RuleBody, request: Request, user: dict = Depends(require(*CONFIGURE))):
    await _check(request, body)
    st = request.app.state
    row = await st.pool.fetchrow(
        """INSERT INTO rule (name, scope_asset_id, scope_profile_id, condition, action, enabled)
           VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
        body.name, body.scope_asset_id, body.scope_profile_id, body.condition, body.action, body.enabled)
    await st.pool.execute(
        "INSERT INTO audit_log (username, entity, action, new) VALUES ($1, $2, 'rule.create', $3)",
        user["username"], f"rule:{row['id']}", body.model_dump())
    await st.engine.load_rules()
    return dict(row)


async def _clear_rule_alarms(st, rule_id: int) -> None:
    for a in await st.pool.fetch("SELECT entity_id, type FROM alarm WHERE rule_id = $1 AND cleared_at IS NULL",
                                 rule_id):
        await st.alarms.clear(entity_id=a["entity_id"], type=a["type"])


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, body: RuleBody, request: Request, user: dict = Depends(require(*CONFIGURE))):
    await _check(request, body)
    st = request.app.state
    old = await st.pool.fetchrow("SELECT * FROM rule WHERE id = $1", rule_id)
    if old is None:
        raise HTTPException(404, "no such rule")
    row = await st.pool.fetchrow(
        """UPDATE rule SET name = $2, scope_asset_id = $3, scope_profile_id = $4, condition = $5,
               action = $6, enabled = $7, updated_at = now() WHERE id = $1 RETURNING *""",
        rule_id, body.name, body.scope_asset_id, body.scope_profile_id, body.condition, body.action, body.enabled)
    await st.pool.execute(
        "INSERT INTO audit_log (username, entity, action, old, new) VALUES ($1, $2, 'rule.update', $3, $4)",
        user["username"], f"rule:{rule_id}",
        {k: old[k] for k in ("name", "scope_asset_id", "scope_profile_id", "condition", "action", "enabled")},
        body.model_dump())
    # Alarms from the old definition would never clear under the new one.
    await _clear_rule_alarms(st, rule_id)
    await st.engine.load_rules()
    return dict(row)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, request: Request, user: dict = Depends(require(*CONFIGURE))):
    st = request.app.state
    old = await st.pool.fetchrow("DELETE FROM rule WHERE id = $1 RETURNING *", rule_id)
    if old is None:
        raise HTTPException(404, "no such rule")
    await st.pool.execute(
        "INSERT INTO audit_log (username, entity, action, old) VALUES ($1, $2, 'rule.delete', $3)",
        user["username"], f"rule:{rule_id}", {k: old[k] for k in ("name", "condition", "action")})
    await _clear_rule_alarms(st, rule_id)
    await st.engine.load_rules()


@router.get("/audit")
async def audit(request: Request, entity: str | None = None, limit: int = Query(200, le=5000),
                _: dict = Depends(require(*CONFIGURE))):
    return records(await request.app.state.pool.fetch(
        "SELECT * FROM audit_log WHERE ($1::text IS NULL OR entity = $1) ORDER BY id DESC LIMIT $2",
        entity, limit))
