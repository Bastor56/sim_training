"""
Mock domain data for the claim fraud investigation agent. No real APIs, no DB.

Answer key (for Phase 6 verification against the agent's decisions):
- CLM-1001 is clean: normal claimant history, weather corroborates the
  claimed hail damage. Should resolve quickly to "approve".
- CLM-1042 is suspicious: repeat filer, flagged repair shop, and the
  weather record contradicts the claimed cause of damage. Should require
  more tool calls and land on "deny" or "escalate".
- CLM-1103 is clean: normal claimant history, weather corroborates the
  claimed flood damage. Should resolve quickly to "approve".
- CLM-1207 is suspicious: repeat filer near policy limits each time,
  flagged repair shop, and the weather record contradicts the claimed
  lightning-caused fire. Should require more tool calls and land on
  "deny" or "escalate".
"""

POLICIES = {
    "POL-001": {
        "policy_id": "POL-001",
        "claimant_id": "CUST-100",
        "coverage_type": "auto_comprehensive",
        "limit": 25000,
        "start_date": "2022-03-01",
    },
    "POL-002": {
        "policy_id": "POL-002",
        "claimant_id": "CUST-200",
        "coverage_type": "auto_comprehensive",
        "limit": 30000,
        "start_date": "2024-11-15",
    },
    "POL-003": {
        "policy_id": "POL-003",
        "claimant_id": "CUST-300",
        "coverage_type": "auto_comprehensive",
        "limit": 20000,
        "start_date": "2023-07-20",
    },
    "POL-004": {
        "policy_id": "POL-004",
        "claimant_id": "CUST-400",
        "coverage_type": "auto_liability",
        "limit": 15000,
        "start_date": "2025-02-10",
    },
}

CLAIMS = {
    "CLM-1001": {
        "claim_id": "CLM-1001",
        "policy_id": "POL-001",
        "claimant_id": "CUST-100",
        "claimed_amount": 3200,
        "damage_type": "hail damage",
        "incident_date": "2026-05-02",
        "incident_location": "Dallas, TX",
        "repair_shop_id": "SHOP-A",
    },
    "CLM-1042": {
        "claim_id": "CLM-1042",
        "policy_id": "POL-002",
        "claimant_id": "CUST-200",
        "claimed_amount": 18000,
        "damage_type": "hail damage",
        "incident_date": "2026-06-10",
        "incident_location": "Austin, TX",
        "repair_shop_id": "SHOP-B",
    },
    "CLM-1103": {
        "claim_id": "CLM-1103",
        "policy_id": "POL-003",
        "claimant_id": "CUST-300",
        "claimed_amount": 4500,
        "damage_type": "flood damage",
        "incident_date": "2026-04-18",
        "incident_location": "Houston, TX",
        "repair_shop_id": "SHOP-C",
    },
    "CLM-1207": {
        "claim_id": "CLM-1207",
        "policy_id": "POL-004",
        "claimant_id": "CUST-400",
        "claimed_amount": 14500,
        "damage_type": "lightning-caused fire damage",
        "incident_date": "2026-07-22",
        "incident_location": "Phoenix, AZ",
        "repair_shop_id": "SHOP-D",
    },
}

CLAIM_HISTORY = {
    "CUST-100": [
        {
            "claim_id": "CLM-0871",
            "claimed_amount": 900,
            "damage_type": "windshield chip",
            "incident_date": "2024-08-14",
            "status": "paid",
        },
    ],
    "CUST-200": [
        {
            "claim_id": "CLM-0912",
            "claimed_amount": 27500,
            "damage_type": "collision",
            "incident_date": "2025-01-22",
            "status": "paid",
        },
        {
            "claim_id": "CLM-0977",
            "claimed_amount": 22000,
            "damage_type": "theft",
            "incident_date": "2025-07-09",
            "status": "paid",
        },
        {
            "claim_id": "CLM-1005",
            "claimed_amount": 26000,
            "damage_type": "vandalism",
            "incident_date": "2026-01-30",
            "status": "paid",
        },
    ],
    "CUST-300": [
        {
            "claim_id": "CLM-0654",
            "claimed_amount": 1100,
            "damage_type": "windshield chip",
            "incident_date": "2024-02-03",
            "status": "paid",
        },
    ],
    "CUST-400": [
        {
            "claim_id": "CLM-0888",
            "claimed_amount": 14200,
            "damage_type": "fire damage",
            "incident_date": "2025-05-11",
            "status": "paid",
        },
        {
            "claim_id": "CLM-0951",
            "claimed_amount": 13800,
            "damage_type": "collision",
            "incident_date": "2025-11-03",
            "status": "paid",
        },
    ],
}

# Documented for completeness, but check_repair_shop_reputation always
# raises ToolError (Phase 2) regardless of this table — it's the lab's
# designated always-fails tool for the forced-failure/backoff demo.
REPAIR_SHOPS = {
    "SHOP-A": {
        "repair_shop_id": "SHOP-A",
        "reputation_score": 8.5,
        "flags": [],
    },
    "SHOP-B": {
        "repair_shop_id": "SHOP-B",
        "reputation_score": 3.2,
        "flags": ["frequent high-value estimates", "under investigation"],
    },
    "SHOP-C": {
        "repair_shop_id": "SHOP-C",
        "reputation_score": 9.0,
        "flags": [],
    },
    "SHOP-D": {
        "repair_shop_id": "SHOP-D",
        "reputation_score": 2.5,
        "flags": ["recently opened", "cash-only settlements reported"],
    },
}

WEATHER_RECORDS = {
    ("Dallas, TX", "2026-05-02"): {
        "conditions": "severe thunderstorms with golf-ball-sized hail",
        "corroborates_claim": True,
    },
    ("Austin, TX", "2026-06-10"): {
        "conditions": "clear and sunny, no precipitation",
        "corroborates_claim": False,
    },
    ("Houston, TX", "2026-04-18"): {
        "conditions": "heavy rain and flash flooding",
        "corroborates_claim": True,
    },
    ("Phoenix, AZ", "2026-07-22"): {
        "conditions": "clear, no lightning activity recorded",
        "corroborates_claim": False,
    },
}
