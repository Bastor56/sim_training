"""LangGraph's state for day 4's per-turn graph.

Unlike day 2/3's AgentState/GraphState -- one long-running investigation,
many iterations inside a *single* graph.invoke() call -- this GraphState
represents an entire chat session: graph.invoke() is called once per
turn, and LangGraph's checkpointer (see graph.py's InMemorySaver, keyed
by session_id as the thread_id) persists state between those calls. That
checkpointer is the actual mechanism behind "conversation state must
persist across turns within a session." Day 3's tradeoffs.md flagged
checkpointing as "a capability LangGraph ships but this port never turns
on, because day 2 never needed it" -- day 4 is the first lab with a real
multi-turn requirement, so this is where it actually gets turned on.

turns reuses conversation_state.py's Turn dataclass directly (Phase 3),
the same way day 3 imported day 2's Observation unchanged into its own
GraphState -- only the container gets LangGraph's reducer treatment; the
item type doesn't change shape at all.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, List, Optional

from conversation_state import Turn
from decision import Decision
from tool_client import ToolOutcome


@dataclass
class GraphState:
    session_id: str
    customer_id: str

    # Fetched once at session bootstrap (see graph.py's bootstrap_session),
    # never per-turn -- see its own docstring for why.
    customer_accounts: List[dict] = field(default_factory=list)

    # The session's turn history. Every response_node call returns exactly
    # one new Turn as {"turns": [new_turn]}; operator.add appends it to
    # what the checkpointer already restored, rather than overwriting it.
    turns: Annotated[List[Turn], operator.add] = field(default_factory=list)

    # In-flight fields for the turn currently being processed -- plain
    # local variables in a hand-rolled loop (day 2's
    # `action = planner(state)` equivalent), promoted to state fields
    # because LangGraph nodes can only hand information to the next node
    # through returned state, never through a shared local variable.
    pending_user_message: str = ""
    pending_decision: Optional[Decision] = None
    pending_tool_outcome: Optional[ToolOutcome] = None
