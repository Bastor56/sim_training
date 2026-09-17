import context  # noqa: F401
import json
import unittest
from dataclasses import dataclass
from typing import Any

from planner import PlannerContractError, plan_next_action, validate_action
from state import AgentState


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 5


@dataclass
class FakeBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list
    usage: FakeUsage


class FakeMessagesClient:
    """Stands in for anthropic.Anthropic().messages — no network call."""

    def __init__(self, reply_text: str):
        self.reply_text = reply_text
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse(content=[FakeBlock(text=self.reply_text)], usage=FakeUsage())


class ValidateActionTests(unittest.TestCase):
    def test_valid_call_tool_action_passes(self):
        action = {
            "action": "call_tool",
            "tool": "get_policy_details",
            "args": {"policy_id": "POL-001"},
            "reasoning": "need the policy first",
        }
        self.assertEqual(validate_action(action), action)

    def test_valid_terminate_action_passes(self):
        action = {"action": "terminate", "decision": "approve", "reasoning": "all clear"}
        self.assertEqual(validate_action(action), action)

    def test_non_dict_raises(self):
        with self.assertRaises(PlannerContractError):
            validate_action(["not", "a", "dict"])

    def test_unknown_action_kind_raises(self):
        with self.assertRaises(PlannerContractError):
            validate_action({"action": "wander_off"})

    def test_call_tool_unregistered_tool_raises(self):
        with self.assertRaises(PlannerContractError):
            validate_action({"action": "call_tool", "tool": "nonexistent_tool", "args": {}})

    def test_call_tool_missing_required_arg_raises(self):
        with self.assertRaises(PlannerContractError):
            validate_action({"action": "call_tool", "tool": "get_policy_details", "args": {}})

    def test_terminate_invalid_decision_raises(self):
        with self.assertRaises(PlannerContractError):
            validate_action({"action": "terminate", "decision": "maybe", "reasoning": "unsure"})

    def test_terminate_missing_reasoning_raises(self):
        with self.assertRaises(PlannerContractError):
            validate_action({"action": "terminate", "decision": "approve"})


class PlanNextActionTests(unittest.TestCase):
    def setUp(self):
        self.state = AgentState(goal="investigate CLM-1001", claim_id="CLM-1001")

    def test_valid_call_tool_response_is_parsed_and_tokens_counted(self):
        reply = json.dumps(
            {
                "action": "call_tool",
                "tool": "get_policy_details",
                "args": {"policy_id": "POL-001"},
                "reasoning": "start with the policy",
            }
        )
        client = FakeMessagesClient(reply)

        action = plan_next_action(self.state, client=client)

        self.assertEqual(action["tool"], "get_policy_details")
        self.assertEqual(self.state.tokens_used, 15)
        self.assertEqual(len(client.calls), 1)

    def test_valid_terminate_response_is_parsed(self):
        reply = json.dumps({"action": "terminate", "decision": "deny", "reasoning": "fraud confirmed"})
        client = FakeMessagesClient(reply)

        action = plan_next_action(self.state, client=client)

        self.assertEqual(action["decision"], "deny")

    def test_malformed_json_raises_planner_contract_error(self):
        client = FakeMessagesClient("this is not json")
        with self.assertRaises(PlannerContractError):
            plan_next_action(self.state, client=client)

    def test_well_formed_json_wrong_shape_raises_planner_contract_error(self):
        client = FakeMessagesClient(json.dumps({"action": "call_tool", "tool": "ghost_tool", "args": {}}))
        with self.assertRaises(PlannerContractError):
            plan_next_action(self.state, client=client)


if __name__ == "__main__":
    unittest.main()
