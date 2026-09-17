"""Tool implementations against the mock domain data in mock_data.py."""

from __future__ import annotations

from typing import Any

import mock_data as data
from errors import ToolError


def get_policy_details(policy_id: str) -> dict[str, Any]:
    policy = data.POLICIES.get(policy_id)
    if policy is None:
        raise ToolError(f"no policy found for policy_id={policy_id!r}")
    return policy


def get_claim_history(claimant_id: str) -> list[dict[str, Any]]:
    return data.CLAIM_HISTORY.get(claimant_id, [])


def check_repair_shop_reputation(repair_shop_id: str) -> dict[str, Any]:
    # Designated always-fails tool: simulates a flaky third-party reputation
    # service for the forced-failure/backoff deliverable (plan.md Phase 7).
    raise ToolError(
        f"repair shop reputation service unavailable (repair_shop_id={repair_shop_id!r})"
    )


def check_weather_conditions(location: str, date: str) -> dict[str, Any]:
    record = data.WEATHER_RECORDS.get((location, date))
    if record is None:
        raise ToolError(f"no weather record for location={location!r} date={date!r}")
    return record
