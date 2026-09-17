import context  # noqa: F401
import unittest

from loop import run_agent
from state import AgentState


class TerminationOnPlannerSignalTests(unittest.TestCase):
    def test_planner_terminates_immediately(self):
        def planner(state):
            return {"action": "terminate", "decision": "approve", "reasoning": "clean"}

        state = AgentState(goal="g", claim_id="CLM-1001")
        final = run_agent(state, planner=planner)

        self.assertEqual(final.status, "terminated_success")
        self.assertEqual(final.final_decision, {"decision": "approve", "reasoning": "clean"})
        self.assertEqual(final.iteration_count, 1)
        self.assertEqual(final.observations, [])


class GoldenPathTests(unittest.TestCase):
    def test_two_tools_then_terminate(self):
        script = [
            {
                "action": "call_tool",
                "tool": "get_policy_details",
                "args": {"policy_id": "POL-001"},
            },
            {
                "action": "call_tool",
                "tool": "get_claim_history",
                "args": {"claimant_id": "CUST-100"},
            },
            {"action": "terminate", "decision": "approve", "reasoning": "history is clean"},
        ]
        calls = {"n": 0}

        def planner(state):
            action = script[calls["n"]]
            calls["n"] += 1
            return action

        state = AgentState(goal="g", claim_id="CLM-1001")
        final = run_agent(state, planner=planner)

        self.assertEqual(final.status, "terminated_success")
        self.assertEqual(len(final.observations), 2)
        self.assertEqual(final.observations[0].tool, "get_policy_details")
        self.assertEqual(final.observations[1].tool, "get_claim_history")
        self.assertIsNone(final.observations[0].error)
        self.assertIsNone(final.observations[1].error)
        self.assertEqual(final.iteration_count, 3)


class ForcedFailureTests(unittest.TestCase):
    def test_flaky_tool_retries_then_loop_terminates_cleanly(self):
        # First turn: call the always-fails tool. Second turn: the planner
        # sees the error observation and escalates instead of retrying
        # forever — proving a tool failure becomes an observation the
        # planner can reason about, not a crash.
        script = [
            {
                "action": "call_tool",
                "tool": "check_repair_shop_reputation",
                "args": {"repair_shop_id": "SHOP-B"},
            },
            {"action": "terminate", "decision": "escalate", "reasoning": "reputation check unavailable"},
        ]
        calls = {"n": 0}

        def planner(state):
            action = script[calls["n"]]
            calls["n"] += 1
            return action

        state = AgentState(goal="g", claim_id="CLM-1042")
        final = run_agent(state, planner=planner)

        self.assertEqual(final.status, "terminated_success")
        self.assertEqual(final.final_decision["decision"], "escalate")
        self.assertEqual(len(final.observations), 1)
        self.assertIsNotNone(final.observations[0].error)
        self.assertIn("unavailable", final.observations[0].error)


class LoopCannotRunForeverTests(unittest.TestCase):
    def test_planner_that_never_terminates_is_stopped_by_iteration_cap(self):
        # A planner that always asks for another tool call must still be
        # cut off by the iteration cap — this is the "prove the loop
        # cannot run forever" deliverable.
        def planner(state):
            return {
                "action": "call_tool",
                "tool": "check_repair_shop_reputation",
                "args": {"repair_shop_id": "SHOP-B"},
            }

        state = AgentState(goal="g", claim_id="CLM-1042", max_iterations=4)
        final = run_agent(state, planner=planner)

        self.assertEqual(final.status, "terminated_iteration_limit")
        self.assertEqual(final.iteration_count, 4)
        self.assertEqual(len(final.observations), 4)
        self.assertTrue(all(o.error is not None for o in final.observations))

    def test_token_budget_stops_the_loop(self):
        def planner(state):
            state.tokens_used += 100  # mirrors plan_next_action's real side effect
            return {"action": "call_tool", "tool": "get_claim_history", "args": {"claimant_id": "CUST-100"}}

        state = AgentState(goal="g", claim_id="CLM-1001", max_iterations=1000, token_budget=250)
        final = run_agent(state, planner=planner)

        self.assertEqual(final.status, "terminated_budget_limit")
        self.assertLess(final.iteration_count, 1000)

    def test_wall_clock_budget_stops_the_loop(self):
        def planner(state):
            return {"action": "call_tool", "tool": "get_claim_history", "args": {"claimant_id": "CUST-100"}}

        state = AgentState(
            goal="g",
            claim_id="CLM-1001",
            max_iterations=1000,
            wall_clock_budget_seconds=0.0,
        )
        final = run_agent(state, planner=planner)

        self.assertEqual(final.status, "terminated_budget_limit")
        self.assertEqual(final.iteration_count, 0)


if __name__ == "__main__":
    unittest.main()
