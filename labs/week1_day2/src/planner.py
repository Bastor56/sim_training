"""Planner: one LLM call that reads agent state and returns exactly one of
two JSON shapes — call_tool or terminate. See spec.md 'Planner contract'.

The Anthropic client is injectable (the `client` param) specifically so
unit tests can exercise validate_action() and the prompt-building without
making a real network call.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from registry import REGISTRY
from state import AgentState

MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024
DECISIONS = {"approve", "deny", "escalate"}


class PlannerContractError(Exception):
    """The planner's response didn't satisfy the two-shape contract: not
    JSON, an unregistered tool, missing required args, or an invalid
    decision. Per spec.md this is harness-visible — raised, not silently
    retried or guessed around."""


def default_client() -> Any:
    return anthropic.Anthropic().messages


def _tool_catalog() -> str:
    return "\n".join(
        f"- {name}(schema={spec['schema']}): {spec['description']}"
        for name, spec in REGISTRY.items()
    )


SYSTEM_PROMPT_TEMPLATE = """You are investigating an insurance claim for potential fraud.

Available tools:
{tool_catalog}

On every turn, respond with exactly one JSON object and nothing else, in one of these two shapes:

{{"action": "call_tool", "tool": "<tool name>", "args": {{...matches that tool's schema...}}, "reasoning": "..."}}
{{"action": "terminate", "decision": "approve" | "deny" | "escalate", "reasoning": "..."}}

Keep investigating (call_tool) while evidence is ambiguous: a repeat claimant, a flagged repair shop, or weather that contradicts the claimed cause of damage are all reasons to dig further. Terminate once you are confident in a decision. Never call the same tool with the same arguments twice."""


def _format_observations(state: AgentState) -> str:
    if not state.observations:
        return "(no observations yet)"
    lines = []
    for obs in state.observations:
        outcome = f"result={obs.result}" if obs.error is None else f"error={obs.error}"
        lines.append(f"- {obs.tool}({obs.args}) -> {outcome}")
    return "\n".join(lines)


def validate_action(action: Any) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise PlannerContractError(f"planner output was not a JSON object: {action!r}")

    kind = action.get("action")
    if kind == "call_tool":
        tool = action.get("tool")
        if tool not in REGISTRY:
            raise PlannerContractError(f"planner named an unregistered tool: {tool!r}")
        args = action.get("args")
        if not isinstance(args, dict):
            raise PlannerContractError(f"call_tool action for {tool!r} is missing an args object")
        required = REGISTRY[tool]["schema"].get("required", [])
        missing = [f for f in required if f not in args]
        if missing:
            raise PlannerContractError(f"call_tool for {tool!r} missing required args: {missing}")
        return action
    if kind == "terminate":
        if action.get("decision") not in DECISIONS:
            raise PlannerContractError(
                f"terminate action had invalid decision: {action.get('decision')!r}"
            )
        if "reasoning" not in action:
            raise PlannerContractError("terminate action is missing reasoning")
        return action
    raise PlannerContractError(f"planner action must be 'call_tool' or 'terminate', got: {kind!r}")


def plan_next_action(state: AgentState, client: Any | None = None) -> dict[str, Any]:
    messages_client = client or default_client()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(tool_catalog=_tool_catalog())
    user_prompt = (
        f"Goal: {state.goal}\n\n"
        f"Observations so far:\n{_format_observations(state)}\n\n"
        "What is your next action?"
    )

    response = messages_client.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=1,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    state.tokens_used += response.usage.input_tokens + response.usage.output_tokens

    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        action = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlannerContractError(f"planner did not return valid JSON: {text!r}") from exc

    return validate_action(action)
