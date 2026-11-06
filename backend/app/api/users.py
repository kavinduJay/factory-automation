from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import records
from .auth import MANAGE_USERS, ROLES, current_user, hash_password, make_token, require, verify_password

router = APIRouter(prefix="/api")


class Login(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class NewUser(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = ""
    password: str = Field(min_length=8)
    role: str


class UserPatch(BaseModel):
    display_name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


@router.post("/auth/login")
async def login(body: Login, request: Request):
    row = await request.app.state.pool.fetchrow(
        "SELECT username, display_name, role, password_hash FROM app_user WHERE username = $1 AND active",
        body.username)
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "wrong username or password")
    return {"token": make_token(row["username"]),
            "user": {"username": row["username"], "display_name": row["display_name"], "role": row["role"]}}


@router.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


@router.post("/auth/password")
async def change_password(body: PasswordChange, request: Request, user: dict = Depends(current_user)):
    pool = request.app.state.pool
    stored = await pool.fetchval("SELECT password_hash FROM app_user WHERE id = $1", user["id"])
    if not verify_password(body.old_password, stored):
        raise HTTPException(400, "old password is wrong")
    await pool.execute("UPDATE app_user SET password_hash = $2 WHERE id = $1",
                       user["id"], hash_password(body.new_password))
    return {"ok": True}


@router.get("/users")
async def list_users(request: Request, _: dict = Depends(require(*MANAGE_USERS))):
    return records(await request.app.state.pool.fetch(
        "SELECT id, username, display_name, role, active, created_at FROM app_user ORDER BY username"))


@router.post("/users", status_code=201)
async def create_user(body: NewUser, request: Request, user: dict = Depends(require(*MANAGE_USERS))):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(ROLES)}")
    pool = request.app.state.pool
    if await pool.fetchval("SELECT 1 FROM app_user WHERE username = $1", body.username):
        raise HTTPException(409, "username taken")
    row = await pool.fetchrow(
        """INSERT INTO app_user (username, display_name, password_hash, role) VALUES ($1, $2, $3, $4)
           RETURNING id, username, display_name, role, active, created_at""",
        body.username, body.display_name or body.username, hash_password(body.password), body.role)
    await pool.execute(
        "INSERT INTO audit_log (username, entity, action, new) VALUES ($1, $2, 'user.create', $3)",
        user["username"], f"user:{body.username}", {"role": body.role})
    return dict(row)


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UserPatch, request: Request,
                      user: dict = Depends(require(*MANAGE_USERS))):
    if body.role is not None and body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(ROLES)}")
    pool = request.app.state.pool
    old = await pool.fetchrow("SELECT username, display_name, role, active FROM app_user WHERE id = $1", user_id)
    if old is None:
        raise HTTPException(404, "no such user")
    if user_id == user["id"] and (body.active is False or (body.role and body.role not in MANAGE_USERS)):
        raise HTTPException(400, "you cannot lock yourself out")
    row = await pool.fetchrow(
        """UPDATE app_user SET display_name = coalesce($2, display_name), role = coalesce($3, role),
               active = coalesce($4, active), password_hash = coalesce($5, password_hash)
           WHERE id = $1 RETURNING id, username, display_name, role, active, created_at""",
        user_id, body.display_name, body.role, body.active,
        hash_password(body.password) if body.password else None)
    changes = body.model_dump(exclude_none=True)
    if "password" in changes:
        changes["password"] = "(changed)"
    await pool.execute(
        "INSERT INTO audit_log (username, entity, action, old, new) VALUES ($1, $2, 'user.update', $3, $4)",
        user["username"], f"user:{old['username']}", {k: old[k] for k in changes if k in old.keys()}, changes)
    return dict(row)
