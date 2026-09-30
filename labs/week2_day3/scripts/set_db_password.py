"""Set the harbor_mcp role's password from mcp_server/.env (spec.md "Backend credentials").

The migration creates harbor_mcp WITHOUT a password, so no password is ever
committed. This script is the one place a password is applied, and it reads
it from the server's gitignored .env. Re-run it after every `supabase db reset`
if the role was recreated (it's harmless to run twice).

It connects as the local Supabase admin (the documented local-dev default
postgres:postgres) and refuses to run against anything but localhost, so it
can never touch the remote project the CLI is linked to.

    uv run python scripts/set_db_password.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg import sql

LAB_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = LAB_DIR / "mcp_server" / ".env"
ADMIN_URL = os.environ.get("SUPABASE_LOCAL_ADMIN_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not name.strip().startswith("#"):
            values[name.strip()] = value.strip().strip("\"'")
    return values


def main() -> int:
    if urlparse(ADMIN_URL).hostname not in ("127.0.0.1", "localhost"):
        print(f"refusing: admin URL is not local ({urlparse(ADMIN_URL).hostname})", file=sys.stderr)
        return 1
    env = read_env(ENV_FILE)
    user, password = env.get("HARBOR_DB_USER", ""), env.get("HARBOR_DB_PASSWORD", "")
    if not user or not password or password == "replace-me":
        print(f"HARBOR_DB_USER / HARBOR_DB_PASSWORD missing in {ENV_FILE}", file=sys.stderr)
        return 1
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        # ALTER ROLE can't take bind parameters, so the name and password are
        # quoted by psycopg's sql module, never pasted into the string.
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(user), sql.Literal(password)))
    print(f"password set for role {user}")  # never print the password itself
    return 0


if __name__ == "__main__":
    sys.exit(main())
