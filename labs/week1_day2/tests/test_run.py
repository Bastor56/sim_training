import context  # noqa: F401
import unittest

from mock_data import CLAIMS
from run import build_state


class BuildStateTests(unittest.TestCase):
    def test_goal_includes_every_field_a_tool_could_need(self):
        # Regression test: an earlier version of build_state left out
        # incident_date/incident_location/repair_shop_id, which silently
        # made check_weather_conditions and check_repair_shop_reputation
        # uncallable — the planner had no location/date/shop to pass them.
        for claim_id, claim in CLAIMS.items():
            state = build_state(claim_id)
            for field in (
                "policy_id",
                "claimant_id",
                "claimed_amount",
                "damage_type",
                "incident_date",
                "incident_location",
                "repair_shop_id",
            ):
                self.assertIn(
                    str(claim[field]),
                    state.goal,
                    f"{claim_id}: goal is missing {field}={claim[field]!r}",
                )

    def test_unknown_claim_id_exits(self):
        with self.assertRaises(SystemExit):
            build_state("CLM-DOES-NOT-EXIST")


if __name__ == "__main__":
    unittest.main()
