import context  # noqa: F401
import unittest

from errors import ToolError
import tools


class ToolTests(unittest.TestCase):
    def test_get_policy_details_known(self):
        policy = tools.get_policy_details("POL-001")
        self.assertEqual(policy["claimant_id"], "CUST-100")

    def test_get_policy_details_unknown_raises_tool_error(self):
        with self.assertRaises(ToolError):
            tools.get_policy_details("POL-999")

    def test_get_claim_history_known(self):
        history = tools.get_claim_history("CUST-200")
        self.assertEqual(len(history), 3)

    def test_get_claim_history_unknown_returns_empty_list_not_error(self):
        # No prior claims is a normal outcome, not a failure.
        self.assertEqual(tools.get_claim_history("CUST-999"), [])

    def test_check_repair_shop_reputation_always_fails(self):
        # Designated flaky tool for the forced-failure/backoff demo.
        with self.assertRaises(ToolError):
            tools.check_repair_shop_reputation("SHOP-A")
        with self.assertRaises(ToolError):
            tools.check_repair_shop_reputation("SHOP-DOES-NOT-EXIST")

    def test_check_weather_conditions_known(self):
        record = tools.check_weather_conditions("Austin, TX", "2026-06-10")
        self.assertFalse(record["corroborates_claim"])

    def test_check_weather_conditions_unknown_raises_tool_error(self):
        with self.assertRaises(ToolError):
            tools.check_weather_conditions("Nowhere, TX", "2000-01-01")


if __name__ == "__main__":
    unittest.main()
