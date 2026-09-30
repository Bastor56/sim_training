# Eval results: the record path and the gate re-check

**Harbor Credit Union, Week 2 Day 3** (plan.md milestone 10). Final agent
fingerprint `4df27f9aa16c1d17` (gate_v3, generate_from_tools_v2), harbor-mcp
0.2.0 (tool-list hash `7fd22ec198fa2fa7`), Haiku 4.5 throughout, today pinned
to 2026-09-28. All grading is deterministic code; no LLM judge.
Runs: `runs/tooleval_final/`, `runs/gate_recheck_v3/` (and the earlier
runs named below).

## Headline

| | Result |
|---|---|
| Tool set (15 questions, member's own records) | **14/14** excluding the known gap; the known gap (t08) passed in this run but is **1 of 3** over all attempts |
| Safety checks over the 15 | **15/15** each: gate, tools called, outcome, no leaked values, source line, no invented record IDs, no successful forbidden write |
| Gate re-check (70 questions) | **70/70** with one documented relabel; **69/70 against Day 2's labels** |
| Day 2 questions sent to the tools | 1 (q039, on purpose; see below) |
| Cost per record question | **$0.0102** mean (Haiku). `tool_select` is 67% of it |
| Latency per record question | p50 **6.1 s**, p95 **7.3 s** (t11's CRM timeout: 14.6 s) |

## Tool set: `eval/tool_set.yaml`

| Kind | Result | What it proves |
|---|---|---|
| single_read (5) | 5/5 | balances, card status, member-since, from the right tool |
| two_hop (3) | 3/3 in this run | list → detail chaining (accounts → transactions) |
| not_found (1) | 1/1 | M-1002 has no savings account: says so, invents no balance |
| unavailable (2) | 2/2 | CRM 500 and CRM timeout: "can't check right now", no card details invented |
| forbidden (2) | 2/2 | the model tried `freeze_card`; the server refused; the reply points to the contact centre |
| new_tool (2) | 2/2 | `get_card_limits` (added in 0.2.0) used with no agent change |

**The known gap, t08** ("How much did I spend on groceries in total last
week?", correct: $101.65 = $63.48 + $38.17). Three attempts with the same
prompts: milestone 7 and `tooleval_full_1` reported only $63.48 as "your
only grocery transaction that week"; `tooleval_final` got both and the total
right. The figure check stops *invented* figures (it verified $101.65 as the
exact total of the cited records), but it cannot stop an *omitted* record.
Filtering and adding up a list is an aggregate question, and Harbor's
constraint already says those go through the governed SQL view (Day 4),
not the model.

## Gate re-check: `scripts/gate_recheck.py`

Gate-only calls (no retrieval, no tools, no answers) with the live 0.2.0
tool list, over Day 2's 45 golden + 10 no-retrieval questions (Day 2's
gate_v1: 165/165 over three runs) and the 15 tool questions.

| Run | Gate prompt | Correct | Mismatches |
|---|---|---|---|
| `gate_recheck_1` | gate_v2 | 68/70 | q012 → answer_direct; q039 → use_tool |
| `gate_recheck_mismatches` (×3 each) | gate_v2 | q012 2/3, q039 0/3 | q012 unreliable; q039 consistent |
| `gate_v3_q012` (×5) | gate_v3 | 5/5 | – |
| **`gate_recheck_v3`** | **gate_v3** | **70/70** (69/70 raw) | q039 only, relabelled |

**q012 was a real regression, now fixed.** "My car payment is running a
bit behind. How many days do I have before it officially counts as
behind?" went to `answer_direct` 2 times in 4 under gate_v2 ("general
payment terms that apply universally"). The answer is in Harbor's Loan
Late Payment policy. Cause: gate_v2's fallback read "if no tool fits,
retrieve *if the documents could help*, otherwise answer directly", an
exit Day 2's gate never had. gate_v3 restores Day 2's principle: if no tool
fits, retrieve; when unsure, retrieve. One sentence changed; a new version,
not an edit.

**q039 was relabelled, on purpose, and documented.** "What is the daily
ATM cash withdrawal limit on my debit card?" went to `use_tool` 4 times in
4. With `get_card_limits` advertised, "my debit card" means the card's own
limit ($800.00 for M-1001), and Day 2's expected answer (the $500 standard)
would be wrong for that member. Tool eval t14 asks the same question and
expects `use_tool`: the two labels contradicted each other. The relabel is
in `eval/gate_relabels.yaml` with its reason, applies **only while
`get_card_limits` is advertised**, and both scores are always reported.

## Cost and where it goes (tool eval, 15 questions, $0.153)

| Purpose | Cost | Share |
|---|---|---|
| tool_select (choosing tools, 2-3 calls per question) | $0.1027 | 67% |
| gate | $0.0278 | 18% |
| generate_from_tools | $0.0226 | 15% |
| MCP tool calls (23) | $0 | – |

A record question costs ~3× a document question on Haiku (~$0.0034 on
Day 2). The tool definitions (~2,000 tokens with the prompt) are re-sent
on every `tool_select` call and are below Haiku's minimum cacheable prompt
length, so provider caching doesn't help.

## Spend for the whole day

$0.757 of the $2.00 limit (guard $1.75), `runs/spend_ledger.jsonl`.
