"""Every dollar figure in a record answer must be traceable to a cited record (milestone 7 decision).

The citation guard proves the records an answer cites are real. It can't
prove a number *computed* from them is right: on the first live run the
model cited three real grocery transactions ($63.48, $38.17, $42.10) and
reported their total as $144.75 (it is $143.75). This check closes that
gap, deterministically and at no API cost.

A figure in the answer passes if it equals (ignoring sign):
  - a money value in one of the cited records (a balance, an amount), or
  - the exact total of the cited records' transaction amounts: all of
    them, the money-out ones, or the money-in ones.
Anything else is "unverified" and the answer is withheld.

Money in the records is a 2-decimal string ("-63.48"; see the manifest),
so comparison is exact Decimal arithmetic, never float.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# "$4,210.55", "$ 30", "-$63.48", "$1,200". Figures without a $ sign (dates, IDs, counts) aren't money.
_FIGURE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?")
_MONEY = re.compile(r"^-?\d+\.\d{2}$")
TWO = Decimal("0.01")


def figures_in(text: str) -> list[Decimal]:
    out = []
    for whole, frac in _FIGURE.findall(text):
        out.append(Decimal(whole.replace(",", "") + (frac or "")).quantize(TWO))
    return out


def _dicts(data: Any):
    """Every dict inside a tool result, however nested."""
    if isinstance(data, dict):
        yield data
        for v in data.values():
            yield from _dicts(v)
    elif isinstance(data, list):
        for v in data:
            yield from _dicts(v)


def cited_records(results: list[dict], cited_ids: set[str]) -> list[dict]:
    """The record dicts (from successful tool results) that carry one of the cited IDs."""
    found: dict[int, dict] = {}
    for r in results:
        for d in _dicts(r["data"]):
            if any(isinstance(v, str) and v in cited_ids for v in d.values()):
                found[id(d)] = d
    return list(found.values())


def _money(value: Any) -> Decimal | None:
    if isinstance(value, str) and _MONEY.match(value):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def allowed_figures(records: list[dict]) -> set[Decimal]:
    values = [m for d in records for m in (_money(v) for v in d.values()) if m is not None]
    amounts = [m for d in records if (m := _money(d.get("amount"))) is not None]
    allowed = {abs(v) for v in values}
    if amounts:
        allowed |= {abs(sum(amounts)),
                    abs(sum((a for a in amounts if a < 0), Decimal(0))),
                    sum((a for a in amounts if a > 0), Decimal(0))}
    return {a.quantize(TWO) for a in allowed}


def check(answer: str, results: list[dict], cited_ids: set[str]) -> dict:
    """{"figures": [...], "unverified": [...]} as strings. Empty "unverified" means the answer passes."""
    figures = figures_in(answer)
    allowed = allowed_figures(cited_records(results, cited_ids))
    unverified = [f for f in figures if f not in allowed]
    return {"figures": [str(f) for f in figures], "unverified": [str(f) for f in unverified]}
