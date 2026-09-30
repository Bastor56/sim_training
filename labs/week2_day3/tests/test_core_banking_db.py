"""The harbor_mcp role can read core banking and nothing else (plan.md milestone 1).

Live tests against local Supabase Postgres; skipped when it isn't running.
Setup: `npx supabase db reset --local`, then `uv run python scripts/set_db_password.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from set_db_password import ADMIN_URL, ENV_FILE, read_env  # noqa: E402


def _url(user: str, password: str, env: dict) -> str:
    return f"postgresql://{user}:{password}@{env['HARBOR_DB_HOST']}:{env['HARBOR_DB_PORT']}/{env['HARBOR_DB_NAME']}"


@pytest.fixture(scope="module")
def env() -> dict:
    return read_env(ENV_FILE)


@pytest.fixture(scope="module")
def mcp_conn(env):
    try:
        conn = psycopg.connect(_url(env["HARBOR_DB_USER"], env["HARBOR_DB_PASSWORD"], env), connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.skip(f"local Postgres not reachable as harbor_mcp: {e}")
    yield conn
    conn.close()


def test_can_read_both_tables(mcp_conn):
    assert mcp_conn.execute("select count(*) from harbor_core.accounts").fetchone()[0] == 7
    assert mcp_conn.execute("select count(*) from harbor_core.transactions").fetchone()[0] == 17
    mcp_conn.rollback()


def test_cannot_read_other_schemas(mcp_conn):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        mcp_conn.execute("select * from public.policies")
    mcp_conn.rollback()


@pytest.mark.parametrize("statement", [
    "update harbor_core.accounts set balance = 0",
    "insert into harbor_core.transactions values ('TXN-X', 'ACC-2001', '2026-09-28', 1, 'x', 'x')",
    "delete from harbor_core.transactions",
])
def test_cannot_write(mcp_conn, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        mcp_conn.execute(statement)
    mcp_conn.rollback()


def test_wrong_password_is_rejected(env, mcp_conn):
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(_url(env["HARBOR_DB_USER"], "not-the-password", env), connect_timeout=3)


def test_week1_policies_survived_the_reset(mcp_conn):
    with psycopg.connect(ADMIN_URL, connect_timeout=3) as admin:
        assert admin.execute("select count(*) from public.policies").fetchone()[0] == 5
