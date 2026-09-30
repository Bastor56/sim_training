"""The audit log: one JSON line per tool call (spec.md "Audit log", R5).

Append-only. Written by the middleware for every tools/call, allowed or not,
and by the HTTP wrapper for requests refused before MCP (401). Tools run in
worker threads, so writes take a lock to keep lines whole.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_audit_id() -> str:
    return f"aud_{uuid.uuid4().hex[:16]}"


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
