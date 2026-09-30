"""Fingerprint of everything that decides the agent's behaviour: agent/*.py and prompts/*.md.

Used by the discovery demo (plan.md milestone 8, R2): the same fingerprint
before and after the server gains a tool proves the agent was not changed.
A hash of the files themselves, rather than a git commit, so it also
covers uncommitted edits.

    uv run python scripts/agent_fingerprint.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent.parent


def files() -> list[Path]:
    return sorted([*LAB_DIR.glob("agent/*.py"), *LAB_DIR.glob("prompts/*.md")])


def fingerprint() -> str:
    h = hashlib.sha256()
    for p in files():
        h.update(p.relative_to(LAB_DIR).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


if __name__ == "__main__":
    print(f"{fingerprint()}  ({len(files())} files: agent/*.py, prompts/*.md)")
