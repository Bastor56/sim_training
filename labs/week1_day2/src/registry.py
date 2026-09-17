"""Tool registry: name -> callable + typed parameter schema + description.

Adding a tool means adding an entry here — the loop, executor, and planner
prompt-builder all read from this dict and never need to change.
"""

from __future__ import annotations

from typing import Any

import tools

REGISTRY: dict[str, dict[str, Any]] = {
    "get_policy_details": {
        "fn": tools.get_policy_details,
        "schema": {
            "type": "object",
            "properties": {"policy_id": {"type": "string"}},
            "required": ["policy_id"],
        },
        "description": "Look up a policy record by policy_id.",
    },
    "get_claim_history": {
        "fn": tools.get_claim_history,
        "schema": {
            "type": "object",
            "properties": {"claimant_id": {"type": "string"}},
            "required": ["claimant_id"],
        },
        "description": "List a claimant's prior claims.",
    },
    "check_repair_shop_reputation": {
        "fn": tools.check_repair_shop_reputation,
        "schema": {
            "type": "object",
            "properties": {"repair_shop_id": {"type": "string"}},
            "required": ["repair_shop_id"],
        },
        "description": "Check a repair shop's reputation score and flags.",
    },
    "check_weather_conditions": {
        "fn": tools.check_weather_conditions,
        "schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["location", "date"],
        },
        "description": (
            "Check recorded weather conditions for a location/date, to "
            "corroborate or contradict a claimed cause of damage."
        ),
    },
}
