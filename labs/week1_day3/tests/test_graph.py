import context  # noqa: F401
import unittest

from langgraph.types import RetryPolicy

from graph import build_graph
from graph_state import GraphState

# day 2's executor.py let tests inject a fake `sleep` so backoff-mechanics
# tests didn't have to eat the real 0.5/1.0/2.0s delays. LangGraph's
# RetryPolicy has no such hook -- the sleep is hardcoded inside the
# framework's own retry runner. The only lever tests have is the policy's
# own timing config, so this fast policy exists purely to keep these tests
# quick; graph.py's default EXECUTOR_RETRY_POLICY (used by run.py) is the
# one that actually matches day 2's curve.
import bootstrap  # noqa: F401,E402
from errors import ToolError  # noqa: E402

FAST_RETRY_POLICY = RetryPolicy(
    initial_interval=0.01, backoff_factor=1.0, max_attempts=3, jitter=False, retry_on=ToolError
)


class TerminationOnPlannerSignalTests(unittest.TestCase):
    def test_planner_terminates_immediately(self):
        def fake_planner(shim):
            return {"action": "terminate", "decision": "approve", "reasoning": "clean"}

        graph = build_graph(plan_fn=fake_planner, retry_policy=FAST_RETRY_POLICY)
        final = graph.invoke(GraphState(goal="g", claim_id="CLM-1001"))

        self.assertEqual(final["status"], "terminated_success")
        self.assertEqual(final["final_decision"], {"decision": "approve", "reasoning": "clean"})
        self.assertEqual(final["iteration_count"], 1)
        self.assertEqual(final["observations"], [])


class GoldenPathTests(unittest.TestCase):
    def test_two_tools_then_terminate(self):
        script = [
            {"action": "call_tool", "tool": "get_policy_details", "args": {"policy_id": "POL-001"}},
            {"action": "call_tool", "tool": "get_claim_history", "args": {"claimant_id": "CUST-100"}},
            {"action": "terminate", "decision": "approve", "reasoning": "history is clean"},
        ]
        calls = {"n": 0}

        def fake_planner(shim):
            action = script[calls["n"]]
            calls["n"] += 1
            return action

        graph = build_graph(plan_fn=fake_planner, retry_policy=FAST_RETRY_POLICY)
        final = graph.invoke(GraphState(goal="g", claim_id="CLM-1001"))

        self.assertEqual(final["status"], "terminated_success")
        self.assertEqual(len(final["observations"]), 2)
        self.assertEqual(final["observations"][0].tool, "get_policy_details")
        self.assertEqual(final["observations"][1].tool, "get_claim_history")
        self.assertIsNone(final["observations"][0].error)
        self.assertIsNone(final["observations"][1].error)
        self.assertEqual(final["iteration_count"], 3)


class ForcedFailureTests(unittest.TestCase):
    def test_flaky_tool_retries_via_retry_policy_then_loop_terminates_cleanly(self):
        # Same scenario as day 2's forced-failure demo: turn 1 calls the
        # always-fails tool, turn 2 escalates once the exhausted-retry
        # observation is visible to the planner.
        script = [
            {
                "action": "call_tool",
                "tool": "check_repair_shop_reputation",
                "args": {"repair_shop_id": "SHOP-B"},
            },
            {"action": "terminate", "decision": "escalate", "reasoning": "reputation check unavailable"},
        ]
        calls = {"n": 0}

        def fake_planner(shim):
            action = script[calls["n"]]
            calls["n"] += 1
            return action

        graph = build_graph(plan_fn=fake_planner, retry_policy=FAST_RETRY_POLICY)
        final = graph.invoke(GraphState(goal="g", claim_id="CLM-1042"))

        self.assertEqual(final["status"], "terminated_success")
        self.assertEqual(final["final_decision"]["decision"], "escalate")
        self.assertEqual(len(final["observations"]), 1)
        self.assertIsNotNone(final["observations"][0].error)
        self.assertIn("unavailable", final["observations"][0].error)


class LoopCannotRunForeverTests(unittest.TestCase):
    def test_planner_that_never_terminates_is_stopped_by_iteration_cap(self):
        def fake_planner(shim):
            return {
                "action": "call_tool",
                "tool": "check_repair_shop_reputation",
                "args": {"repair_shop_id": "SHOP-B"},
            }

        graph = build_graph(plan_fn=fake_planner, retry_policy=FAST_RETRY_POLICY)
        final = graph.invoke(GraphState(goal="g", claim_id="CLM-1042", max_iterations=4))

        self.assertEqual(final["status"], "terminated_iteration_limit")
        self.assertEqual(final["iteration_count"], 4)
        self.assertEqual(len(final["observations"]), 4)
        self.assertTrue(all(o.error is not None for o in final["observations"]))

    def test_token_budget_stops_the_loop(self):
        def fake_planner(shim):
            shim.tokens_used += 100  # mirrors plan_next_action's real side effect
            return {"action": "call_tool", "tool": "get_claim_history", "args": {"claimant_id": "CUST-100"}}

        graph = build_graph(plan_fn=fake_planner, retry_policy=FAST_RETRY_POLICY)
        final = graph.invoke(
            GraphState(goal="g", claim_id="CLM-1001", max_iterations=1000, token_budget=250)
        )

        self.assertEqual(final["status"], "terminated_budget_limit")
        self.assertLess(final["iteration_count"], 1000)

    def test_wall_clock_budget_stops_the_loop(self):
        def fake_planner(shim):
            return {"action": "call_tool", "tool": "get_claim_history", "args": {"claimant_id": "CUST-100"}}

        graph = build_graph(plan_fn=fake_planner, retry_policy=FAST_RETRY_POLICY)
        final = graph.invoke(
            GraphState(
                goal="g",
                claim_id="CLM-1001",
                max_iterations=1000,
                wall_clock_budget_seconds=0.0,
            )
        )

        self.assertEqual(final["status"], "terminated_budget_limit")
        self.assertEqual(final["iteration_count"], 0)


if __name__ == "__main__":
    unittest.main()
