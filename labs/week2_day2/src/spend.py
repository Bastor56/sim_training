"""The day's spend ledger and the budget guard (spec.md "Spend guard", decision 11).

runs/spend_ledger.jsonl gets one line per *provider* call, from every run,
development and pilots included. It is committed, so the day's total is
auditable. llm.call() checks the total before each provider call and raises
BudgetExceeded once it reaches the guard ($3.50, leaving headroom under the
$4.00 day limit). Local-cache hits and local models cost nothing and are not
in the ledger.

    uv run python src/spend.py          # totals by run and by purpose
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import settings


class BudgetExceeded(RuntimeError):
    """The ledger total, or this run's own cap, has been reached."""


def ledger_path() -> Path:
    # Read at call time so tests can point settings.SPEND_LEDGER_PATH elsewhere.
    return settings.SPEND_LEDGER_PATH


def entries(path: Path | None = None) -> list[dict]:
    path = path or ledger_path()
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def total(path: Path | None = None) -> float:
    return round(sum(e["cost_usd"] for e in entries(path)), 6)


def append(entry: dict, path: Path | None = None) -> None:
    path = path or ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def check(guard: float | None = None, run_spend: float = 0.0, run_cap: float | None = None) -> None:
    """Raise before a provider call if the day's guard or the run's cap is reached."""
    guard = settings.BUDGET_GUARD_USD if guard is None else guard
    spent = total()
    if spent >= guard:
        raise BudgetExceeded(f"spend ledger at ${spent:.4f} >= guard ${guard:.2f}; no more provider calls today")
    if run_cap is not None and run_spend >= run_cap:
        raise BudgetExceeded(f"this run has spent ${run_spend:.4f} >= its --max-spend ${run_cap:.2f}")


def summary(path: Path | None = None) -> str:
    rows = entries(path)
    by_run: dict[str, float] = defaultdict(float)
    by_purpose: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    for e in rows:
        by_run[e["run_id"]] += e["cost_usd"]
        by_purpose[e["purpose"]] += e["cost_usd"]
        by_model[e["model"]] += e["cost_usd"]
    spent = sum(e["cost_usd"] for e in rows)
    lines = [f"provider calls: {len(rows)}   total spend: ${spent:.4f}   "
             f"guard ${settings.BUDGET_GUARD_USD:.2f}   day limit ${settings.DAY_LIMIT_USD:.2f}   "
             f"remaining to guard: ${settings.BUDGET_GUARD_USD - spent:.4f}"]
    for title, table in (("by run", by_run), ("by purpose", by_purpose), ("by model", by_model)):
        lines.append(f"\n{title}:")
        lines += [f"  {k:45s} ${v:.4f}" for k, v in sorted(table.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
