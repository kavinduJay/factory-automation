"""Simple login: scrypt password hashes and HMAC-signed bearer tokens.

Roles (docs/ARCHITECTURE.md): owner, manager, operator, admin.
  - every role: view everything, acknowledge alarms
  - owner, manager, admin: change settings and rules, correct weighings, edit batches
  - owner, admin: manage users
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, HTTPException, Request, WebSocket, status

from ..config import settings

ROLES = ("owner", "manager", "operator", "admin")
CONFIGURE = ("owner", "manager", "admin")
MANAGE_USERS = ("owner", "admin")

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r),
                             p=int(p), dklen=len(dk) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), dk)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign(body: str) -> str:
    return _b64(hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).digest())


def make_token(username: str, ttl_s: int | None = None) -> str:
    body = _b64(json.dumps({"u": username, "exp": int(time.time()) + (ttl_s or settings.token_ttl_s)}).encode())
    return f"{body}.{_sign(body)}"


def read_token(token: str) -> str | None:
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, TypeError):
        return None
    return data["u"] if data.get("exp", 0) > time.time() else None


async def user_for_token(pool, token: str | None) -> dict | None:
    username = read_token(token) if token else None
    if not username:
        return None
    row = await pool.fetchrow(
        "SELECT id, username, display_name, role FROM app_user WHERE username = $1 AND active", username)
    return dict(row) if row else None


async def current_user(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else None
    user = await user_for_token(request.app.state.pool, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require(*roles: str):
    async def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"needs role {' or '.join(roles)}")
        return user
    return dep


async def ws_user(ws: WebSocket) -> dict | None:
    return await user_for_token(ws.app.state.pool, ws.query_params.get("token"))


async def bootstrap_admin(pool, username: str, password: str | None) -> bool:
    """Create the first user (role admin) if there are no users yet."""
    if not password or await pool.fetchval("SELECT count(*) FROM app_user"):
        return False
    await pool.execute(
        "INSERT INTO app_user (username, display_name, password_hash, role) VALUES ($1, $1, $2, 'admin')",
        username, hash_password(password))
    return True
