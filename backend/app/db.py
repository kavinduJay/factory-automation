"""asyncpg pool with JSON codecs."""
import json
from datetime import date, datetime
from decimal import Decimal

import asyncpg


def json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"not JSON serialisable: {type(o)}")


def dumps(o) -> str:
    return json.dumps(o, default=json_default, ensure_ascii=False)


async def _init(conn: asyncpg.Connection) -> None:
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=10, init=_init)


def record(r) -> dict | None:
    return dict(r) if r is not None else None


def records(rs) -> list[dict]:
    return [dict(r) for r in rs]
