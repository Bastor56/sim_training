"""Start the Harbor mock CRM on :8100 with ONLY its API key (backends/mock_crm/contract.md).

The key lives in the MCP server's .env, because the server is the CRM's one
legitimate caller. This launcher copies just CRM_API_KEY into the CRM
process's environment, so the CRM never sees the database password or the
MCP caller tokens that share that file.

    uv run python scripts/run_crm.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

from set_db_password import ENV_FILE, read_env

LAB_DIR = Path(__file__).resolve().parent.parent
CRM_DIR = LAB_DIR / "backends" / "mock_crm"
PORT = 8100


def main() -> int:
    key = read_env(ENV_FILE).get("CRM_API_KEY", "")
    if not key or key == "replace-me":
        print(f"CRM_API_KEY missing in {ENV_FILE}", file=sys.stderr)
        return 1
    os.environ["CRM_API_KEY"] = key
    uvicorn.run("app:app", app_dir=str(CRM_DIR), host="127.0.0.1", port=PORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
