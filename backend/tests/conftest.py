"""Test fixtures. DB tests build a scratch database from db/*.sql with psql,
exactly as the TimescaleDB container does on first start.

Inside the stack:  docker compose run --rm backend pytest
Locally:           TEST_DB_ADMIN_URL=postgresql://tf01:pw@localhost:5432/postgres pytest
"""
import os
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest

from app.alarms import AlarmService
from app.db import create_pool
from app.ingest.service import Ingest
from app.registry import Registry

DB_DIR = Path(os.environ.get("DB_DIR", "/db" if Path("/db").is_dir() else
                             Path(__file__).resolve().parents[2] / "db"))
ADMIN_URL = os.environ.get("TEST_DB_ADMIN_URL") or os.environ.get("DATABASE_URL")

RESET_TABLES = ("telemetry", "telemetry_latest", "alarm", "audit_log", "ingest_msg", "ingest_reject",
                "event_log", "drier_output", "stage_weighing", "crate_weighing", "sack_weighing",
                "area_cycle", "delivery", "batch", "supplier", "app_user")


class FakeHub:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)

    def of(self, type_):
        return [m for m in self.messages if m["type"] == type_]


def _with_db(url: str, name: str) -> str:
    return urlunparse(urlparse(url)._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
async def db_url():
    if not ADMIN_URL:
        pytest.skip("no database: set TEST_DB_ADMIN_URL or DATABASE_URL")
    name = f"tf01_test_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_with_db(ADMIN_URL, "postgres"))
    await admin.execute(f'CREATE DATABASE "{name}"')
    url = _with_db(ADMIN_URL, name)
    try:
        for f in sorted(DB_DIR.glob("*.sql")):
            subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-d", url, "-f", str(f)],
                           check=True, capture_output=True, text=True)
        yield url
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@pytest.fixture(scope="session")
async def pool(db_url):
    p = await create_pool(db_url)
    yield p
    await p.close()


@pytest.fixture
async def clean(pool):
    await pool.execute(f"TRUNCATE {', '.join(RESET_TABLES)} RESTART IDENTITY CASCADE")
    await pool.execute("UPDATE device SET online = false, last_seen = NULL, status_changed_at = NULL")
    await pool.execute("DELETE FROM attribute WHERE scope = 'client'")
    yield pool


@pytest.fixture
async def stack(clean):
    """Registry, fake hub, alarms and ingest over a clean database."""
    registry = Registry()
    await registry.load(clean)
    hub = FakeHub()
    alarms = AlarmService(clean, hub)
    ingest = Ingest(clean, registry, alarms, hub, "tf01")

    class S:
        pass
    s = S()
    s.pool, s.registry, s.hub, s.alarms, s.ingest = clean, registry, hub, alarms, ingest
    return s


def pytest_collection_modifyitems(items):
    # Run every async test on the session loop that owns the pool.
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if "asyncio" in item.keywords or getattr(item, "obj", None) and \
                __import__("inspect").iscoroutinefunction(item.obj):
            item.add_marker(marker, append=False)
