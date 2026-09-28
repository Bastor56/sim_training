# FDE Xlerate - Week 2, Day 2
Build plan: agentic RAG, the instrumentation wrapper, and the three-model comparison (Harbor Credit Union)

See `spec.md` for the design (agent graph, validator, instrumentation
rules, cache equivalence rule, grading, budget). This is the build
order. Each milestone should be working and verified before you start
the next.

**Why this order:**
- The wrapper is built **before** the agent. Every LLM call the agent
  makes has to go through it (R4), and retrofitting a wrapper is how
  calls end up bypassing it.
- The riskiest unknown comes right after that: whether the pinned SDK
  (`anthropic==0.104.1`) accepts each model's configuration (structured
  output, `effort`, disabled thinking, fallbacks). It's tested with a
  handful of cents of real calls in milestone 2, before anything is built
  on top of it.
- Money is spent late and deliberately. Unit tests use a **fake client**
  (no network, no cost). The full runs happen only after a 5-question
  pilot has measured the real cost per question.

**Decisions 12-14** (spec.md "Decision record: 12-14") were added after
the milestone 4 prompt review: a generator decline triggers a rewrite; a
code-added source line on every reply; a version-in-force check. The
milestones below include them.

**⏸ PAUSE** marks a point where you should stop, look at the output
yourself, and decide whether to continue before building on top of it.

**💲** marks a step that spends real API money. Run `uv run python
src/spend.py` after each one. The guard stops everything at $3.50; the
day's limit is $4.00.

All commands run from `labs/week2_day2/`.

## Milestone 0 — Environment, Day 6 bridge, pinned prices

- [x] Folders: `src/`, `tests/`, `eval/`, `prompts/`, `cache/llm/`,
      `runs/`, `artifacts/`
- [x] `.python-version` (3.12), `pytest.ini` (copy Day 6's), `.gitignore`
      (`.venv/`, `runs/*/tmp/`). **Not** `cache/llm/` or
      `runs/spend_ledger.jsonl`, which are committed on purpose.
- [x] `requirements.txt`: `-r ../week2_day1/requirements.txt` plus
      `langgraph==1.2.11` (week 1's pin). Create the venv and install.
- [x] Check the Day 6 index exists: `../week2_day1/index/chroma` and
      `../week2_day1/index/bm25` for `layout / B_structure`. If it's
      missing, rebuild it with Day 6's `ingest.py` (offline captions, no
      API calls).
- [x] `src/day6.py`: puts `../week2_day1/src` on `sys.path` (**after**
      Day 2's `src`), then re-exports `Retriever`, `access_filter`,
      `load_golden_set`/`matches`/`relevant_items` from `golden`, and the
      golden-set path. No other Day 2 file imports a Day 6 module
      directly.
- [x] `tests/conftest.py`: Day 2 `src/` first on `sys.path`, then Day 6's
- [x] `src/settings.py`: paths, `MAX_ROUNDS = 3`, `TAU_KEEP = 0.10`,
      `TOP_K = 5`, model roles (spec table), Opus `max_tokens = 4000`,
      `BUDGET_GUARD_USD = 3.50`, `DAY_LIMIT_USD = 4.00`,
      `PARSER = "layout"`, `CHUNKER = "B_structure"`
- [x] **Pricing, from the live page, not from memory.** Open
      `https://platform.claude.com/docs/en/about-claude/pricing` and copy,
      for Haiku 4.5, Sonnet 5 and Opus 5: input, output, 5-minute cache
      write and cache read (USD per million tokens) into `pricing.json`,
      with `source_url`, `retrieved_on: 2026-09-25` and
      `pricing_version: "2026-09-25"`. Sanity check against the spec's
      reference figures. If they differ, the live page wins, and you note
      it in `artifacts/findings_log.md`.

**Verify:**
```bash
uv run python -c "import langgraph, anthropic, chromadb; print('ok')"
uv run python -c "import day6; r = day6.Retriever('layout','B_structure'); print([x.metadata['doc_id'] for x in r.search('What is the fee for a stop payment?', top_k=3).results])"
uv run pytest   # 0 tests, no errors
```

**Checkpoint:** the Day 6 retriever answers from inside Day 2's venv with
no network. `pricing.json` has 3 models × 4 rates, each traceable to the
page.

## Milestone 1 — The wrapper, with a fake client (no spend)

The heart of R4 and R5. Built and tested before any agent code exists.

- [x] `src/pricing.py`: `load()`, `cost(model, usage) -> float` using the
      spec's cost formula. Raises `UnknownModelPrice` for a model not in
      the table.
- [x] `src/tracing.py`:
  - `current: ContextVar`;
  - `interaction(correlation_id, billable=True)` context manager;
  - `record_local(purpose, latency_ms, **details)`, which writes a
    `kind="local_model"` record;
  - a `Recorder` that appends records to `runs/<run_id>/calls.jsonl`.
- [x] `src/spend.py`:
  - `total()` over `runs/spend_ledger.jsonl`;
  - `check(guard)`, which raises `BudgetExceeded`;
  - CLI: totals by run and by purpose.
- [x] `src/llm.py`: `call(purpose, model, system, messages, *,
      output_schema=None, thinking=None, effort=None, max_tokens,
      prompt_version, cache_scope) -> LLMResult`
  - raises `NoActiveInteraction` if there's no correlation ID;
  - the order inside `call()`: start the record → (cache: milestone 3,
    a no-op for now) → spend guard → provider → price → write the record
    (in a `finally`, so errors are recorded too);
  - builds the request per model role: `thinking`, `output_config`
    (effort + JSON schema), `fallbacks` for Opus, all via `extra_body`
    where the SDK needs it; no `temperature`;
  - `cache_control` on the system prompt block;
  - parses the structured JSON output; handles `stop_reason`
    (`refusal`, `max_tokens` → a recorded error, not a crash mid-run);
  - takes an injectable `client` for tests;
  - **the only file that imports `anthropic`**.
- [x] `tests/fakes.py`: a `FakeAnthropic` that returns scripted responses
      with a given `usage`, counts calls, and can sleep to fake latency
- [x] `tests/test_no_bypass.py`: parses every `src/*.py` AST;
      `import anthropic` / `from anthropic` is allowed only in `llm.py`;
      no Day 2 module name collides with a Day 6 module name; nothing
      imports Day 6's `captioning`

**Verify:** `uv run pytest tests/test_pricing.py tests/test_tracing.py tests/test_llm.py tests/test_no_bypass.py`
- `cost("claude-haiku-4-5", {input: 1_000_000, output: 0})` equals the
  table's input rate; cache-read and cache-write tokens priced at their
  own rates; an unknown model raises
- a call outside `interaction()` raises; inside one, it writes exactly one
  record with every spec field present
- a fake API error still writes a record (with `error` set)
- guard: a ledger at $3.49 allows a call; at $3.50 it raises
  `BudgetExceeded` **before** the fake client is called
- a `billable=False` interaction writes `billable: false`
- add a stray `import anthropic` to a scratch file in `src/` → the
  no-bypass test fails; remove it

**Checkpoint:** you can explain how one call's `cost_usd` was computed,
from its token counts and `pricing.json`, by hand.

## Milestone 2 — 💲 Live smoke test: does each model accept its config? (highest risk)

About 6 tiny calls, a few cents. Every call goes through `llm.call()`, so
the first real spend is already in the ledger.

- [x] `src/smoke.py`: under one `interaction("smoke/1")`, for each role
      config in the spec, send "Reply with {\"ok\": true}" using that
      role's structured-output schema:
  - Haiku 4.5, no thinking (gate and generator A)
  - Sonnet 5, `thinking: {type: "disabled"}` (generator B and judge)
  - Opus 5, `thinking: {type: "adaptive"}`, `effort: "medium"`,
    `max_tokens: 4000`, fallbacks on (generator C)
- [x] Print per call: accepted? `model_served`, tokens, latency, cost

```bash
uv run python src/smoke.py
uv run python src/spend.py
```

**⏸ PAUSE — read every result.**
- A 400 here means the parameter shape is wrong for that model or for
  SDK 0.104.1. Fix it in `llm.py`'s request builder now, then re-run
  only the failing call.
- The likely suspects:
  - structured output on Haiku 4.5 (if it isn't supported, fall back to
    a JSON-only instruction plus strict parsing, and record the change);
  - `output_config` needing `extra_body`;
  - a thinking/effort combination.
- Check that Opus's `output_tokens` is bigger than the visible reply.
  That's the thinking, billed as output.
- Record anything surprising in `artifacts/findings_log.md`.

**Checkpoint:** three configurations accepted, three records in
`calls.jsonl`, the ledger shows a few cents.

## Milestone 3 — Exact-match cache (no spend)

- [x] `src/llm_cache.py`:
  - `normalise_question()` (NFKC, casefold, collapse whitespace, strip
    trailing `?!.`);
  - `key(parts) -> sha256` over the canonical JSON of: model, thinking,
    effort, max_tokens, output schema, prompt version, rendered system,
    messages with the question normalised, tenant, access scope, corpus
    version;
  - `get`/`put` at `cache/llm/<namespace>/<key>.json`;
  - modes `off` / `read-only` / `read-write`.
- [x] Wire it into `llm.call()`:
  - a hit writes the record with `local_cache: "hit"`, `cost_usd: 0`,
    `cost_basis: "local_cache"`, the lookup latency, and the cached
    response's original token counts kept for information;
  - `read-only` + miss raises `CacheMissReadOnly` (used by replay);
  - the record stores the key, never the question text.

**Verify:** `uv run pytest tests/test_llm_cache.py`
- `"What is the wire fee?"` and `"  what is the WIRE fee "` → same key
- change **one** of tenant / `allow_restricted` / `current_only` /
  corpus version / prompt version / model / effort / one chunk's text →
  a different key (one assertion each)
- `"What is the wire fee?"` vs `"How much does a wire cost?"` → a
  different key (paraphrases miss, by design)
- second identical call: the fake client is called **once** in total;
  two records are written, the second priced $0
- `read-only` mode never calls the client

**Checkpoint:** every row of the spec's "safely equivalent" table has a
test that proves it.

## Milestone 4 — Eval sets and prompts (no spend)

- [x] `eval/no_retrieval_set.yaml`: the 10 questions from the spec
      (n001-n010), each with `expected_gate: answer_direct`,
      `tenant: retail`, `category`, `notes`. Header: `version: 1`,
      `created`.
- [x] `eval/repeat_traffic_set.yaml`: 18 probes, each with
      `source_id`, `variant` (`surface` / `paraphrase` / `tenant_swap` /
      `corpus_change`) and `expect_cache` (`hit` / `miss`). Pick the 8
      surface variants and 5 paraphrases from answerable golden
      questions with different topics.
- [x] `src/eval_sets.py`: loads all three into one `EvalItem` list
      (`id, set, question, tenant, expected_gate, expected_outcome,
      golden_row`). Sets `expected_outcome` from the spec's grading
      table.
- [x] Prompts, each a small versioned file. They contain no dates, IDs or
      anything that changes per request, because those would break both
      caches:
  - `gate_v1.md`: when retrieval is needed (any Harbor-specific fact,
    policy, fee, rate, procedure, product or document) vs not (greetings,
    meta, general knowledge, off-topic). Returns
    `{decision, reason, search_query}`. `search_query` is a keyword-rich
    rewrite of the question.
  - `rewrite_v1.md`: given the queries tried and what came back
    (titles + scores), write a different query. Try other wording,
    Harbor terminology, or narrowing/broadening.
  - `generate_v1.md`: the spec's generator rules, including the named
    near-miss case (right topic, wrong product/version →
    `not_in_corpus`).
  - `direct_answer_v1.md`: helpful and brief. Never state a Harbor fee,
    rate, limit or policy. Offer to look it up instead. Politely decline
    off-topic requests in one line.
  - `judge_v1.md`: the spec's verdict rules.

**Verify:** `uv run pytest tests/test_eval_sets.py`
- 45 + 10 = 55 quality items, 18 repeat probes; ids unique
- expected outcomes: 41 `answered`, 4 `not_in_corpus` (q003, q043-q045),
  10 `answered_direct`
- every repeat probe's `source_id` exists in the golden set

**⏸ PAUSE — read the prompts out loud.** Is anything in the gate prompt
Harbor-specific enough to leak into a direct answer? Does the generator
prompt make "decline" as easy to choose as "answer"? You tune these
before you see eval numbers, not after.

## Milestone 5 — The agent graph, with fakes (no spend)

- [x] `src/agent_state.py`: `AgentState` exactly as in the spec
- [x] `src/validator.py`: `validate(results, tau) -> (kept, verdict)`
- [x] `src/agent_nodes.py`: `planner` (gate on round 0, rewrite after),
      `retrieve` (Day 6 `Retriever`, one shared instance, plus
      `tracing.record_local`), `validate`, `generate` (with the
      ungrounded-answer guard), `answer_direct`, `not_in_corpus`, and
      `finalise`, which adds the code-built source line (decision 13).
      Every node appends its trace event.
- [x] `src/agent_graph.py`: `build_graph(llm_call=llm.call,
      retriever=None)` with the spec's edges, including decision 12: a
      generator decline or ungrounded answer goes back to the planner
      while rounds remain. The round cap is checked in the edge functions.
- [x] Injectable `llm_call` and `retriever`, so tests use a scripted fake
      LLM and a fake retriever that returns chosen scores

**Verify:** `uv run pytest tests/test_validator.py tests/test_agent_graph.py`
- gate says `answer_direct` → 0 retrieval rounds, 1 direct-answer call,
  outcome `answered_direct`
- gate `retrieve` + a good score → 1 round, 1 generate call, `answered`
- **always-poor retriever → exactly 3 rounds, 1 gate + 2 rewrite calls,
  0 generate calls, `not_in_corpus`** (the R2 cap test)
- poor, then good on round 2 → 2 rounds, `queries` holds 2 different
  strings
- generator returns `answered` citing a chunk it wasn't given → the
  round's verdict is `ungrounded`, and it's rewritten (decision 12)
- **generator always declines → exactly 3 rounds, 1 gate + 2 rewrites +
  3 generate calls, `not_in_corpus`** (the second cap test, and the most
  one question can cost)
- declines on round 1, answers on round 2 → `answered`, 1 rescue; the
  rewrite call's input contains the generator's decline reason
- **source line** (decision 13): `answered` → `Source: <title> (version
  <v>, effective <date>)…` built from the cited chunks' metadata, one per
  document; `answered_direct` → the general-information line;
  `not_in_corpus` → "none found … (<n> rounds)". Every `reply` ends with
  one.
- every interaction's trace has a `gate` event with a non-empty reason
- the rollup `cost_usd` equals the sum of billable records (fake usage)

**Checkpoint:** the graph's control flow is proved without a single real
call.

## Milestone 6 — 💲 First live traces (~$0.05)

- [x] `src/run_agent.py "question" [--tenant] [--generator haiku]`:
      runs one question under `interaction("adhoc/<n>")` and prints the
      trace readably:
      gate → round 1 (query, top-5 titles + scores, kept) → rewrite? →
      outcome, answer, citations, cost, latency (LLM vs local split)

```bash
uv run python src/run_agent.py "What is the fee for a stop payment?"
uv run python src/run_agent.py "Hi there!"
uv run python src/run_agent.py "Is there a prepayment penalty if I pay off a Harbor RV loan early?"
uv run python src/run_agent.py "How do I send money to someone at another bank?"
uv run python src/run_agent.py "What is the overdraft fee?"
```

**⏸ PAUSE — read all five traces.** This is the D1 demo, so check it the
way a reviewer would:
- Did "Hi there!" skip retrieval, with a sensible reason?
- Did the RV-loan question end `not_in_corpus`? If the reranker passed
  the auto-loan chunk (it will: 0.55 > τ_keep), did the **generator**
  decline? That's the layered design working. After a decline, did the
  rewrite use the decline reason to search for something different
  (decision 12)? If it answered, the generator prompt's near-miss rule
  needs to be clearer. Fix it now, bump it to `generate_v2.md`, and note
  it.
- Did the overdraft answer quote **v3**, both in the model's prose and in
  the source line (decisions 13-14)?
- Does every reply end with a source line of the right kind?
- Are the costs plausible (fractions of a cent on Haiku)? Is most of the
  latency the reranker?

**Checkpoint:** one question's gate decision, every retrieval round, any
rewrite and the final cost are all visible in one trace.

## Milestone 7 — Grading (no spend until the calibration step)

- [x] `src/grading.py`:
  - deterministic checks from the spec: gate confusion, outcome
    correctness, citation hit (Day 6 `golden.matches` against the cited
    chunk texts), version check q028-q031, `version_quoted` +
    `version_in_prose` (decision 14), source line present (decision 13),
    no `$` amount in direct answers, leak check, ungrounded count,
    declines and rescues (decision 12);
  - `judge(interaction)`: Sonnet 5, `purpose=judge`, under a
    `billable=False` interaction, cache namespace `judge`; returns the
    verdict + reason;
  - `task_success` exactly as the spec defines it.
- [x] Writes `runs/<run_id>/grades.jsonl` and fills the grade fields in
      `interactions.jsonl`

**Verify:** `uv run pytest tests/test_grading.py` (fake judge)
- a hand-made interaction citing the q001 expected chunk → citation hit
- q029 citing an `overdraft_policy_v2` chunk → version check fails
- q028 with a reply naming "3.0" only in the source line →
  `version_quoted` ✓, `version_in_prose` ✗; a reply mentioning "v2" →
  `version_quoted` ✗
- a reply with no source line → counted as a violation
- n009 with "$" in the reply → fails the no-amount check
- q044 ending `answered` → outcome wrong, even if the judge would like it
- n005 with 1 retrieval round → gate wrong, outcome wrong
- `task_success` needs outcome ✓ **and** (for answerable) judge `correct`
  **and** citation hit

## Milestone 8 — 💲 Eval runner and the pilot (~$0.25)

- [x] `src/run_eval.py --generator haiku|sonnet|opus --namespace <name>
      [--set golden,no_retrieval|repeat] [--limit N] [--ids ...]
      [--tau 0.10] [--cache read-write|read-only] [--max-spend X]
      [--check-replay]`
  - `run_id = <timestamp>_<generator>_<namespace>`; writes
    `config.json` first (spec "Recorded config")
  - one `interaction("<run_id>/<query_id>")` per question, questions in
    file order
  - after the run: grading (deterministic + judge) and a console summary
  - `summary.md`: task success, gate accuracy, not_in_corpus results,
    cost per interaction (mean / p50 / p95 / max), latency per
    interaction (p50 / p95), cost by purpose, cache hit rate, total spend
- [x] **Pilot:** the same 5 golden questions on all three generators
      (pick a spread: one exact_term, one paraphrase, one scanned_table,
      one version_trap, q045)

```bash
uv run python src/run_eval.py --generator haiku  --namespace pilot --ids q001,q009,q017,q029,q045
uv run python src/run_eval.py --generator sonnet --namespace pilot --ids q001,q009,q017,q029,q045
uv run python src/run_eval.py --generator opus   --namespace pilot --ids q001,q009,q017,q029,q045
uv run python src/spend.py
```

**⏸ PAUSE — the budget decision.** For each model, take the measured mean
cost per question × 55, and add the judge and sweep estimates. Compare
with the spec's budget table.
- If Opus × 55 > $1.20: set Opus to `effort: "low"`, re-pilot Opus only
  (cheap: the gate calls are cache hits), and record both numbers. The
  difference between `medium` and `low` is itself a finding for the
  report.
- If the projected total is above $3.50: drop the τ sweep first.
- Write the projection and the decision in `artifacts/findings_log.md`
  **before** spending on the full runs.

## Milestone 9 — 💲 Haiku runs: baseline, cache, sensitivity (~$0.75)

```bash
uv run python src/run_eval.py --generator haiku --namespace A              # A cold
uv run python src/run_eval.py --generator haiku --namespace A --tag warm   # A warm (hit rate ~100%)
uv run python src/run_eval.py --generator haiku --namespace A --set repeat # repeat-traffic probes
uv run python src/run_eval.py --generator haiku --namespace A_tau005 --tau 0.05
uv run python src/run_eval.py --generator haiku --namespace A_tau030 --tau 0.30
uv run python src/spend.py
```

**⏸ PAUSE — review before running the expensive models.**
- **Gate:** any no-retrieval question that retrieved, or golden question
  that didn't? Read the reasons. A gate mistake here is repeated in all
  three model runs.
- **Rounds:** how many questions needed a rewrite? Did rewrites ever
  *help* (poor → usable)? Find one example for the report.
- **Cache:** warm hit rate ≈ 100%? Repeat probes: all 8 surface variants
  hit, all 5 paraphrases + 3 tenant swaps + 2 corpus changes missed?
  Any mismatch is a key bug. Fix it before going on.
- **Provider caching:** is `cache_read_input_tokens` 0 on Haiku, as the
  4096-token minimum predicts?
- **Leaks:** any restricted or wrong-tenant citation is a stop-and-fix.
- As on Day 6: don't tune prompts to raise the score here. A prompt
  change is a named experiment with a before/after, not a quiet edit.

## Milestone 10 — 💲 Sonnet and Opus runs, judge calibration (~$1.70)

```bash
uv run python src/run_eval.py --generator sonnet --namespace B
uv run python src/run_eval.py --generator opus   --namespace C
uv run python src/spend.py
```

Each run has its own cache namespace, so B and C are genuinely cold. They
pay for their own gate and rewrite calls, just as A did, so the three
cost-per-interaction figures are comparable. The gate is Haiku in all
three runs, so this costs only a few cents per run.

**⏸ PAUSE — calibrate the judge.** For each of runs A, B and C, open 10
judged answers (mix correct / partial / incorrect) next to the golden
`answer`, and write your own verdict first, then compare. Record the
agreement rate (e.g. 27/30) in the findings log. If agreement is poor,
fix `judge_v1.md` → `v2`, re-grade all three runs (costs judge calls
only), and note it. Also check Opus: did any call hit `max_tokens`
(recorded as an error)? How many output tokens were thinking?

## Milestone 11 — Comparison table and replay proof (no spend)

- [x] `src/compare.py --runs <A> <B> <C> [--sweep <A005> <A030>]`
      prints and writes `runs/compare_<ts>.md` + `.json`:
  - **the main table**, one row per model: task success, judge correct %,
    citation hit %, not_in_corpus correct (4 questions), direct-answer
    correct (10 questions), cost per interaction (mean / p95), cost per
    *successful* interaction, latency per interaction (p50 / p95),
    output tokens per generate call (mean, with the thinking share for
    Opus), total run cost
  - cost by purpose (gate / rewrite / generate / direct_answer) and
    latency split (LLM vs local reranker)
  - cache section: cold / warm / repeat-probe hit rates, the probe
    table, provider cache read tokens per model
  - the τ sweep (Haiku): task success, rounds per question, not_in_corpus
    correctness at 0.05 / 0.10 / 0.30
  - the 5 most and least expensive interactions (which questions cost
    the most, and why: rounds? long answers? thinking?)
- [x] Replay proof:

```bash
env -u ANTHROPIC_API_KEY uv run python src/run_eval.py --generator opus --namespace C --cache read-only --check-replay
uv run pytest
```

**Checkpoint:** replay with no API key reproduces run C's interactions
exactly. Every number the report will quote exists in a `runs/` file.

## Milestone 12 — Gate adaptation decision (R7; no spend)

`artifacts/gate_adaptation_decision.md`, 1-2 pages:

- [x] **The call:** what the gate does, its measured accuracy (from the
      confusion table), cost and latency per call (from `calls.jsonl`,
      `purpose=gate`), and the share of cost per interaction it
      represents
- [x] **Option 1, prompt (chosen):** the current cost per call, the one-off
      effort to improve it (prompt edits + re-running the eval), and its
      risks
- [x] **Option 2, RAG over labelled examples:** a bank of labelled
      questions, the 3-5 nearest put into the prompt. Cost: extra input
      tokens per call (estimate from the prompt size), the labelled bank,
      and one embedding lookup.
- [x] **Option 3, fine-tune/distil:** e.g. a logistic-regression
      classifier on the bge-small embeddings we already compute, trained
      on labels produced by the current gate. Cost: labelling N examples
      (N × measured gate cost), near-zero per call, ~ms latency, and
      retraining when topics change. Also: it keeps the question inside
      Harbor (open question 1). Don't claim what isn't measured: 55
      examples are far too few to train on.
- [x] **Verdict: prompt, for now**, with the numbers that justify it
- [x] **What would change the verdict**, stated as thresholds, e.g.
      "distil if volume exceeds X questions/day (gate spend > $Y/month),
      or if gate latency p95 > Z ms matters to the contact centre, or if
      Harbor rules that questions may not leave its environment". Work X
      and Y out from the measured cost per gate call.

## Milestone 13 — Cost/latency comparison report (assignment artifact)

`artifacts/cost_latency_comparison_report.md`, citing the run IDs:

- [x] **Summary:** 3-4 sentences, e.g. "Haiku answered N/55 correctly at
      $X per interaction; Opus with reasoning answered M/55 at $Y (Z×
      the cost) and W× the latency. Recommendation: …"
- [x] **Setup:**
  - task, the 55 questions, the fixed gate/judge models;
  - pinned prices (with source and date);
  - how to replay for $0;
  - **the decision-7 statement on effort as the thinking budget** (spec
    wording)
- [x] **Agentic behaviour:**
  - gate confusion table;
  - rounds distribution;
  - one worked trace where a rewrite rescued a question;
  - q043-q045 and q003 outcomes;
  - ungrounded answers blocked
- [x] **The comparison table** (from `compare.py`) + what deliberation
      bought: which questions Opus got right that Haiku/Sonnet didn't,
      and what that cost in tokens and seconds
- [x] **Cost per interaction:** the distribution, cost by purpose, the
      most expensive questions and why; a monthly projection at an
      assumed volume, **with the assumption stated**
- [x] **Latency:** p50/p95 per model, LLM vs reranker split (the reranker
      as validator costs ~1.5 s per round; it's worth saying so)
- [x] **Cache:**
  - the equivalence rule (spec table, in plain words);
  - cold / warm / probe hit rates;
  - why exact-match (the tenant and version cases);
  - provider prompt caching results per model and why Haiku shows none
- [x] **Validator sensitivity:** the τ sweep
- [x] **Adaptation decision:** a summary + link to
      `gate_adaptation_decision.md`
- [x] **Recommendation** for Harbor: which generator, at which effort,
      and why
- [x] **Limitations:**
  - 55 questions, single runs;
  - τ from the same data;
  - judge from the same family as candidate B (and its calibration
    score);
  - data leaving Harbor;
  - latency from one laptop;
  - the day's total spend from `spend.py`

**Checkpoint:** every number traces to `runs/`. Nothing typed from
memory.

## Milestone 14 — High-level deck (final submission)

`artifacts/high_level_deck.md`, 5-8 slides, same format as Day 6's deck
(`## Slide N: Title`, short bullets, an ASCII diagram or table where it
helps):

- [x] Slide 1: Title / framing (Harbor, Week 2 Day 2: from "retrieve
      always" to "retrieve when it helps", and knowing what each answer
      costs)
- [x] Slide 2: The problem: static RAG's two failures (retrieves
      needlessly, summarises junk), plus the finance question "cost per
      interaction?"
- [x] Slide 3: High-level flow: gate → retrieve → validate → rewrite
      (≤ 3) → answer / not in corpus
- [x] Slide 4: Architecture: the wrapper → cache → guard → provider
      stack, the correlation ID, the two-layer validator
- [x] Slide 5: Tech stack: LangGraph, Day 6 retrieval (Chroma, BM25,
      bge-small, bge-reranker), Claude Haiku 4.5 / Sonnet 5 / Opus 5,
      `pricing.json`, exact-match cache, pytest, uv
- [x] Slide 6: Results: the three-model table (quality × cost × latency)
- [x] Slide 7: Cache, cost per interaction, and the gate adaptation
      verdict
- [x] Slide 8: Known gaps / next (router, member context vs the cache,
      a held-out set for τ, keeping data inside Harbor)

**Done when:** the report, the adaptation decision and the deck are all
under `artifacts/`, citing real runs. `spend.py` shows the day's total is
≤ $4.00.

## Things to watch for (beginner pitfalls)

- **A call that bypasses the wrapper.** The classic case is a quick
  `anthropic.Anthropic()` in a debugging script. The no-bypass test
  scans `src/`, so keep throwaway scripts out of `src/` too, or they
  fail the test. That's the point.
- **Summing latency records to get interaction latency.** Records can
  overlap, and the graph has its own overhead. Interaction latency is
  wall clock around `graph.invoke()`. The records explain where the time
  went.
- **Forgetting thinking tokens.** They're in `output_tokens` and billed
  at the output rate. Opus's visible answer may be short while its bill
  isn't.
- **Timestamps or IDs in prompts.** A `datetime.now()` or a
  correlation ID inside a prompt makes every request unique, and both
  caches silently stop hitting. The ID belongs in the record, never the
  prompt.
- **Letting the model enforce the loop cap.** "Stop after 3 tries" in a
  prompt is a suggestion. `round < MAX_ROUNDS` in the edge function is a
  guarantee.
- **Trusting the reranker to spot unanswerable questions.** Day 6 proved
  it can't (q045). The generator's decline and the citation guard are
  what stop a confident near-miss answer.
- **Letting the judge run up the bill.** Judge calls are real spend even
  though they're `billable: false` to the interaction. They're in the
  ledger, and the guard counts them.
- **Accidentally warm comparison runs.** If a comparison run reuses
  another run's cache namespace, its gate calls cost $0 and it looks
  cheaper than it is. Give each of A, B and C its own namespace. Only the
  deliberate warm rerun of A shares A's.
- **Tuning on the test set.** Same as Day 6: prompt and τ changes are
  named experiments, recorded before and after.
- **Pricing drift.** If Anthropic changes a price, old runs keep the
  `pricing_version` they were priced with. Re-price explicitly; never
  silently.
