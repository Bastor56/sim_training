"""The agent's control flow, proved with fakes (plan.md milestone 5).

LLM calls go through the REAL wrapper (llm.call) with a fake client, so
every call is recorded and priced exactly as in production. The fake client
answers by purpose, recognising which prompt file is in the system block.
The retriever is a fake returning chosen rerank scores per round.
"""

import json
from types import SimpleNamespace

import pytest

import agent_graph
import agent_nodes
import fakes
import settings

CORPUS = "1|test_index"


# ---------------------------------------------------------------- fakes

def chunk(cid, score, doc="fee_schedule_2026", title="Schedule of Fees", version="2026", page=2,
          section="Fees > Account Services", generated=False):
    meta = {"doc_id": doc, "title": title, "version": version, "effective_date": "2026-01-01",
            "page_start": page, "page_end": page, "section_path": section, "contains_generated_text": generated}
    return SimpleNamespace(chunk_id=cid, score=score, text=f"text of {cid}", metadata=meta)


class FakeRetriever:
    """rounds: one list of chunks per retrieval round (the last one repeats)."""

    def __init__(self, rounds):
        self.rounds, self.queries = rounds, []

    def search(self, query, **kw):
        self.queries.append(query)
        results = self.rounds[min(len(self.queries) - 1, len(self.rounds) - 1)]
        return SimpleNamespace(results=results, timings_ms={"rerank": 1.0})


def purpose_of(kwargs):
    system = kwargs["system"][0]["text"]
    for purpose, name in settings.PROMPTS.items():
        if system == agent_nodes.load_prompt(name):
            return purpose
    raise AssertionError("unknown prompt")


class Script:
    """Per-purpose queues of JSON payloads; records each call's purpose and user text."""

    def __init__(self, **queues):
        self.queues = {k: list(v) for k, v in queues.items()}
        self.log: list[tuple[str, str]] = []

    def __call__(self, kwargs):
        purpose = purpose_of(kwargs)
        self.log.append((purpose, kwargs["messages"][0]["content"]))
        queue = self.queues[purpose]
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return fakes.response(payload, input_tokens=1000, output_tokens=100)

    def count(self, purpose):
        return sum(p == purpose for p, _ in self.log)


GATE_RETRIEVE = {"decision": "retrieve", "reason": "asks for a Harbor fee", "search_query": "stop payment fee"}
GATE_DIRECT = {"decision": "answer_direct", "reason": "a greeting", "search_query": ""}
REWRITE = {"search_query": "stop payment order charge", "reason": "use fee-schedule wording"}
DECLINE = {"status": "not_in_corpus", "answer": "", "cited_chunk_ids": [], "reason": "covers auto loans, not RV loans"}


def answer(*cids):
    return {"status": "answered", "answer": "It costs $30.00 per request.", "cited_chunk_ids": list(cids),
            "reason": "the fee schedule lists it"}


def run(lab, script, retriever, question="How much is a stop payment?"):
    lab["client"].default = script
    deps = agent_nodes.AgentDeps(retriever=retriever, generator=settings.GENERATORS["haiku"])
    graph = agent_graph.build_graph(deps)
    return agent_graph.answer_question(graph, correlation_id="test_run/q", question=question,
                                       corpus_version=CORPUS)


GOOD = [chunk("c1", 0.9), chunk("c2", 0.05)]
POOR = [chunk("p1", 0.03), chunk("p2", 0.01)]


# ---------------------------------------------------------------- paths

def test_direct_answer_skips_retrieval(lab):
    script = Script(gate=[GATE_DIRECT], direct_answer=[{"answer": "Hello! How can I help?"}])
    retriever = FakeRetriever([GOOD])
    state, row = run(lab, script, retriever, "Hi there!")
    assert row["outcome"] == "answered_direct" and row["rounds"] == 0 and retriever.queries == []
    assert [p for p, _ in script.log] == ["gate", "direct_answer"]
    assert state.reply.endswith(agent_nodes.DIRECT_SOURCE)


def test_good_first_round_answers(lab):
    script = Script(gate=[GATE_RETRIEVE], generate=[answer("c1")])
    state, row = run(lab, script, FakeRetriever([GOOD]))
    assert row["outcome"] == "answered" and row["rounds"] == 1 and script.count("generate") == 1
    assert row["round_verdicts"] == ["usable"] and [c["chunk_id"] for c in state.citations] == ["c1"]
    # only the usable chunk (0.9 >= 0.10) reached the generator
    generate_input = next(u for p, u in script.log if p == "generate")
    assert "[c1]" in generate_input and "[c2]" not in generate_input


def test_always_poor_hits_the_cap_without_generating(lab):
    """The R2 cap test: 3 rounds, 1 gate + 2 rewrites + 0 generates."""
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[answer("p1")])
    state, row = run(lab, script, FakeRetriever([POOR]))
    assert row["rounds"] == 3 and row["round_verdicts"] == ["poor"] * 3
    assert (script.count("gate"), script.count("rewrite"), script.count("generate")) == (1, 2, 0)
    assert row["outcome"] == "not_in_corpus" and "no chunk scored" in row["outcome_reason"]


def test_always_decline_hits_the_cap_with_three_generates(lab):
    """Decision 12's worst case: 3 rounds, 1 gate + 2 rewrites + 3 generates."""
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[DECLINE])
    state, row = run(lab, script, FakeRetriever([GOOD]))
    assert row["rounds"] == 3 and row["round_verdicts"] == ["declined"] * 3
    assert (script.count("gate"), script.count("rewrite"), script.count("generate")) == (1, 2, 3)
    assert row["outcome"] == "not_in_corpus" and state.reply.startswith(agent_nodes.NOT_IN_CORPUS_REPLY)


def test_poor_then_good_uses_two_different_queries(lab):
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[answer("c1")])
    retriever = FakeRetriever([POOR, GOOD])
    state, row = run(lab, script, retriever)
    assert row["rounds"] == 2 and row["outcome"] == "answered" and row["rewrite_helped"]
    assert retriever.queries == ["stop payment fee", "stop payment order charge"]
    assert not row["rescued_after_decline"]


def test_decline_then_answer_is_a_rescue_and_rewrite_sees_the_reason(lab):
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[DECLINE, answer("c1")])
    state, row = run(lab, script, FakeRetriever([GOOD]))
    assert row["round_verdicts"] == ["declined", "usable"] and row["rescued_after_decline"]
    rewrite_input = next(u for p, u in script.log if p == "rewrite")
    assert "declined: covers auto loans, not RV loans" in rewrite_input


def test_ungrounded_answer_is_blocked_and_rewritten(lab):
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[answer("not_given"), answer("c1")])
    state, row = run(lab, script, FakeRetriever([GOOD]))
    assert row["round_verdicts"] == ["ungrounded", "usable"] and row["outcome"] == "answered"
    assert [c["chunk_id"] for c in state.citations] == ["c1"]


def test_answer_with_no_citations_is_blocked(lab):
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[answer()])
    state, row = run(lab, script, FakeRetriever([GOOD]))
    assert row["round_verdicts"] == ["ungrounded"] * 3 and row["outcome"] == "not_in_corpus"


# ---------------------------------------------------------------- source line (decision 13)

def test_source_line_names_title_version_date_page_and_caption(lab):
    chunks = [chunk("c1", 0.9, doc="overdraft_policy_v3", title="Overdraft Policy", version="3.0", page=-1,
                    section="Overdraft Policy > 4. Overdraft Fees"),
              chunk("c2", 0.8, doc="auto_loan_comparison", title="Auto Loan Comparison", version="",
                    page=1, section="", generated=True)]
    script = Script(gate=[GATE_RETRIEVE], generate=[answer("c1", "c2")])
    state, _ = run(lab, script, FakeRetriever([chunks]))
    assert state.source_line == ("Source: Overdraft Policy (version 3.0, effective 2026-01-01), 4. Overdraft Fees"
                                 " | Auto Loan Comparison (effective 2026-01-01), p.1"
                                 " [includes a model-generated figure caption]")
    assert state.reply == f"It costs $30.00 per request.\n\n{state.source_line}"


def test_source_line_skips_a_section_named_like_the_document(lab):
    chunks = [chunk("c1", 0.9, title="Schedule of Fees", section="Schedule of Fees", page=1)]
    script = Script(gate=[GATE_RETRIEVE], generate=[answer("c1")])
    state, _ = run(lab, script, FakeRetriever([chunks]))
    assert state.source_line == "Source: Schedule of Fees (version 2026, effective 2026-01-01), p.1"


def test_not_in_corpus_source_line_counts_rounds(lab):
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[DECLINE])
    state, _ = run(lab, script, FakeRetriever([POOR]))
    assert state.source_line == "Source: none found. Searched Harbor's documents (3 rounds)."


# ---------------------------------------------------------------- tracing and cost

def _jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_trace_has_gate_reason_and_every_round(lab):
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[DECLINE, answer("c1")])
    run(lab, script, FakeRetriever([GOOD]))
    events = [e["event"] for e in _jsonl(lab["run"].dir / "trace.jsonl")]
    assert events == ["gate", "retrieve", "validate", "generate", "rewrite", "retrieve", "validate",
                      "generate", "outcome"]
    gate = _jsonl(lab["run"].dir / "trace.jsonl")[0]
    assert gate["reason"] == "asks for a Harbor fee" and gate["cid"] == "test_run/q"


def test_rollup_equals_sum_of_billable_records(lab):
    script = Script(gate=[GATE_RETRIEVE], rewrite=[REWRITE], generate=[DECLINE, answer("c1")])
    _, row = run(lab, script, FakeRetriever([GOOD]))
    records = [r for r in _jsonl(lab["run"].dir / "calls.jsonl") if r["correlation_id"] == "test_run/q"]
    assert row["cost_usd"] == pytest.approx(sum(r["cost_usd"] for r in records if r["billable"]))
    assert row["llm_calls"] == 4  # gate, generate, rewrite, generate
    assert sum(r["kind"] == "local_model" for r in records) == 2  # one per retrieval round
    # Haiku: 1,000 in + 100 out = $0.0015 per call
    assert row["cost_usd"] == pytest.approx(4 * 0.0015)
    assert row["cost_by_purpose"] == pytest.approx({"gate": 0.0015, "generate": 0.003, "retrieve": 0.0,
                                                    "rewrite": 0.0015})
