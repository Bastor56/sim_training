import context  # noqa: F401
import unittest

from executor import MAX_ATTEMPTS, UnknownToolError, backoff_delay, execute_tool


class ExecutorSuccessTests(unittest.TestCase):
    def test_successful_call_returns_result_observation_no_sleep(self):
        sleeps = []
        obs = execute_tool("get_policy_details", {"policy_id": "POL-001"}, sleep=sleeps.append)

        self.assertIsNone(obs.error)
        self.assertEqual(obs.result["claimant_id"], "CUST-100")
        self.assertEqual(sleeps, [])  # no retries needed, no backoff delay

    def test_unknown_lookup_is_a_tool_error_not_unknown_tool_error(self):
        # get_policy_details itself raises ToolError for a bad id — that's
        # a recoverable failure the executor should retry, not a harness bug.
        sleeps = []
        obs = execute_tool("get_policy_details", {"policy_id": "POL-999"}, sleep=sleeps.append)

        self.assertIsNotNone(obs.error)
        self.assertIn("POL-999", obs.error)
        self.assertEqual(len(sleeps), MAX_ATTEMPTS - 1)


class ExecutorFlakyToolTests(unittest.TestCase):
    def test_always_failing_tool_retries_then_returns_error_observation(self):
        sleeps = []
        obs = execute_tool(
            "check_repair_shop_reputation", {"repair_shop_id": "SHOP-A"}, sleep=sleeps.append
        )

        self.assertIsNone(obs.result)
        self.assertIsNotNone(obs.error)
        self.assertIn("unavailable", obs.error)
        # Retries happen between attempts, not after the last one.
        self.assertEqual(len(sleeps), MAX_ATTEMPTS - 1)

    def test_backoff_delays_grow(self):
        delays = [backoff_delay(a) for a in range(3)]
        # jitter makes exact values nondeterministic, but the *floor* of
        # each attempt (ignoring jitter) must strictly increase.
        floors = [0.5 * (2**a) for a in range(3)]
        for delay, floor in zip(delays, floors):
            self.assertGreaterEqual(delay, floor)
        self.assertLess(floors[0], floors[1])
        self.assertLess(floors[1], floors[2])


class ExecutorHarnessErrorTests(unittest.TestCase):
    def test_unregistered_tool_raises_unknown_tool_error(self):
        with self.assertRaises(UnknownToolError):
            execute_tool("not_a_real_tool", {}, sleep=lambda _: None)

    def test_bad_arguments_propagate_as_harness_bug_not_swallowed(self):
        # Passing args that don't match the tool's signature is a dispatch
        # bug (should have been caught by planner-output validation), not a
        # recoverable ToolError — it must NOT be retried or turned into an
        # observation.
        with self.assertRaises(TypeError):
            execute_tool("get_policy_details", {"unexpected_kwarg": 1}, sleep=lambda _: None)


if __name__ == "__main__":
    unittest.main()
