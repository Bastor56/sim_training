# Findings log: Week 2, Day 2

Running notes while building, in date order. Anything surprising, any
changed decision, any number the report will need. The report cites
this file; nothing here is typed from memory.

## 2026-09-25

### Milestone 0: environment and prices

- Day 6 retriever loads from Day 2's venv via `src/day6.py`, offline.
  Cold start ~53 s (the first load of the embedder, the reranker and
  Chroma). One smoke query: rerank 2.9 s of the 3.1 s total. The
  reranker dominates retrieval latency, as on Day 6 (~1.5 s warm).
- Prices pinned in `pricing.json` from the live page on 2026-09-25. They
  match the spec's reference figures exactly:

  | Model | Input | Output | 5m cache write | Cache read |
  |---|---|---|---|---|
  | Haiku 4.5 | $1.00 | $5.00 | $1.25 | $0.10 |
  | Sonnet 5 | $2.00 | $10.00 | $2.50 | $0.20 |
  | Opus 5 | $5.00 | $25.00 | $6.25 | $0.50 |

  (USD per million tokens.)
- **Tokenizer caveat for the report:**
  - The pricing page says Claude 4.7+ models (so Sonnet 5 and Opus 5)
    use a newer tokenizer. It produces ~30% more tokens for the same
    text than the tokenizer Haiku 4.5 uses.
  - So *token counts* aren't directly comparable across the three
    candidates. The same prompt costs Sonnet/Opus more tokens.
  - The comparison should lead with **dollars per interaction**, which
    already includes this effect. Token counts appear only per model.

### Milestone 1: the wrapper (no spend)

- 37 unit tests, fake client, no network. The no-bypass test was
  checked by adding a stray `import anthropic as a` in `src/`: it
  failed as intended, then passed again once the file was removed.
- The pinned SDK (`anthropic==0.104.1`) takes `thinking` and
  `output_config` (effort + JSON schema) as named arguments. Only the
  Opus refusal fallback needs `client.beta.messages.create` +
  `extra_body={"fallbacks": "default"}`, as in Day 6's captioning.

### Milestone 2: live smoke test (run `smoke`, $0.0021 total)

| Config | Result | In / out tokens | Latency | Cost |
|---|---|---|---|---|
| Haiku 4.5, no thinking, JSON schema | accepted | 164 / 8 | 5,063 ms (first call: client start-up) | $0.00020 |
| Sonnet 5, thinking disabled, JSON schema | accepted | 221 / 8 | 2,222 ms | $0.00052 |
| Opus 5, adaptive thinking, effort medium, max_tokens 4000, fallbacks | accepted | 221 / 9 | 2,567 ms | $0.00133 |

- **Structured output works on all three**, so no JSON-by-instruction
  fallback is needed.
- **Tokenizer difference visible already:** the same prompt is 164
  tokens on Haiku and 221 on Sonnet/Opus (+35%). This matches the
  pricing page's "~30% more tokens" note for the newer tokenizer.
- **Dated model names:**
  - The API reported `claude-haiku-4-5-20251001` for the requested
    `claude-haiku-4-5`. The wrapper wrongly flagged that as a fallback.
  - The price lookup failed on the dated name, and the wrapper priced
    the call at the requested model's rate with a `pricing_note`. That
    is the same Haiku rate, so the cost is correct.
  - Fixed: `pricing.canonical()` maps a dated snapshot to its alias, and
    a new test covers it.
  - The 3 smoke records predate the fix and keep the old flag; they are
    left as recorded.
- **Opus did not think on a trivial prompt** (9 output tokens at effort
  medium). Adaptive thinking decides per request. The thinking share of
  Opus's cost will only show on real questions (pilot, milestone 8).
- **Provider prompt caching:** 0 cache writes on all three, as expected.
  These system prompts are far below every model's minimum cacheable
  length.

### Milestone 4 pause: prompts reviewed against the lab text → decisions 12-14

The four review questions were checked against
`training_instructions/week2_day2.md` and the week's Harbor constraints.
None was answered outright. Three design changes follow; the full
reasoning is in spec.md "Decision record: 12-14":

- **Decision 12: a generator decline now triggers a rewrite** while
  rounds remain. The lab's architecture routes a failed relevance check
  to "a signal to rewrite", and requires that an irrelevant top-k be
  "detected and acted on". Worst case per question is now 1 gate + 2
  rewrites + 3 generates. `rewrite_v1.md` edited in place to use the
  decline reason. It had never been run, so no cached output depends on
  the old text.
- **Decision 13: a source line on every reply, added by code.** "Every
  answer names the source it came from" covers direct answers too. It's
  code, not a prompt instruction, for the same reason as the citation
  guard. No prompt changed.
- **Decision 14: a `version_quoted` check on q028-q031.** "Policy answers
  quote the policy version in force". The golden answers carry no
  versions, so the judge can't check it. `version_in_prose` is reported
  alongside, so the code-added source line doesn't flatter the model.
- **Gate boundary (question 1) and judge strictness (question 4):** not
  specified by the lab. The current prompts are consistent with the
  Harbor constraints and stay as written.

### Milestone 5: agent graph with fakes (no spend)

- 61 tests passing. The LLM calls in the graph tests go through the
  **real** wrapper with a fake client, so the rollup test checks real
  records.
- Both cap tests hold:
  - always-poor: 3 rounds, 1 gate / 2 rewrites / 0 generates;
  - always-decline: 3 rounds, 1 / 2 / 3.
- No LangGraph checkpointer: one `invoke()` is one single-turn question,
  and nothing carries over between questions.

### Milestone 6: first live traces (run `adhoc`, Haiku, $0.0156 for 5 questions)

| Question | Gate | Rounds | Outcome | Cost | Latency |
|---|---|---|---|---|---|
| stop payment fee | retrieve | 1 | answered: $30.00 per request (q016 ✓) | $0.00285 | 12.2 s (cold start) |
| "Hi there!" | answer_direct | 0 | answered_direct + general-information source line | $0.00134 | 3.1 s |
| RV loan prepayment (q045) | retrieve | 3 (poor, poor, declined) | not_in_corpus ✓ | $0.00403 | 13.9 s |
| send money to another bank | retrieve | 1 | answered: wire, $25 domestic / $45 international, Rev 2026-02 | $0.00364 | 6.8 s |
| overdraft fee | retrieve | 1 | answered: $29 per item, max 3/day, **v3 in prose and in the source line** | $0.00375 | 6.8 s |

- **The layered validator worked on q045.**
  - Rounds 1-2: the reranker rejected the auto-loan chunks (0.052,
    0.095 < 0.10), and the rewrites broadened the search.
  - Round 3: one chunk passed at 0.182, and the **generator declined**
    ("about auto loans, not RV loans").
  - The question ended not_in_corpus without guessing.
  - The decline came in the last round, so decision 12's
    rescue-by-rewrite wasn't exercised here.
- **What the validator's score measures.** Day 6's retriever reranks
  against the search *query* (the gate's/rewrite's wording), not the
  member's question. Rescored locally with the member's question instead:

  | Question | Top chunk | vs agent's query | vs member's words |
  |---|---|---|---|
  | send money to another bank | Wire Transfer Policy | 0.13-0.33 (passes) | 0.003-0.018 (would fail every round) |
  | RV loan prepayment | Auto Loan Comparison | 0.05-0.18 | 0.549 (the Day 6 near miss) |
  | stop payment fee | Fee Schedule | 0.871 | 0.271 |

  Decision: **keep validating against the agent's query.** The gate's
  rewording closes the paraphrase gap Day 6 reported, and it pushes the
  near miss down. Caveat recorded in spec.md: τ = 0.10 came from Day 6's
  question-score distribution, so it isn't calibrated for query scores.
  The τ sweep is the check. Rescoring 5 chunks took 100-370 ms, if it's
  ever wanted.
- **Cost and latency shape on Haiku:**
  - $0.0013-0.0040 per interaction;
  - the gate is ~$0.0009 per question (~25-65% of a question's cost);
  - LLM time (~4.7 s) now exceeds retrieval time (~2.1 s) per question;
  - rough projection for 55 questions on Haiku: **~$0.19**.
- **Source line fix:** the fee schedule's section is named the same as
  the document, so the line repeated the title. It now skips a section
  equal to the title (test added).

### Milestone 7: grading (no spend)

- 82 tests passing. The grader's version check was tested on real
  metadata strings. "version 2026" (the fee schedule) and "Rev 2026-02"
  (the wire policy) must **not** count as naming v2; "(version 3.0, ...)"
  must count as v3.

### Milestone 8: pilot (q001, q009, q017, q029, q045 × 3 generators) → budget decision

Each pilot used its own cache namespace (`pilot_haiku`, `pilot_sonnet`,
`pilot_opus`), not one shared `pilot` namespace as the plan said. With a
shared namespace, Sonnet's and Opus's gate calls would have been free
Haiku cache hits, which would understate their cost per question.

| Generator | Task success | Cost / question (mean) | p95 | Latency p50 | Output tokens / generate | Run spend (incl. judge) |
|---|---|---|---|---|---|---|
| Haiku 4.5 | 5/5 | $0.00321 | $0.00402 | 7.1 s | 115 | $0.0245 |
| Sonnet 5 | 5/5 | $0.00654 | $0.00836 | 7.3 s | 176 | $0.0416 |
| Opus 5 (medium) | 5/5 | $0.01352 | $0.01878 | 9.2 s | 263 | $0.0771 |

- Judge: ~$0.0021-0.0024 per call (Sonnet 5, 4 calls per pilot). It
  costs about as much as a whole Haiku question.
- q045 ended not_in_corpus on all three. On all three, rounds 1-2 were
  "poor", and round 3 was declined by the generator.
- Opus's extra output over Sonnet (same tokenizer): 263 vs 176 tokens
  per generate call. That's a rough upper bound of ~90 thinking tokens
  per answer at effort medium, assuming similar visible answer lengths.
  Opus thinks only a little on these short, factual questions.

**Projection and decision (written before the full runs):**

| Run | Projection |
|---|---|
| A cold (Haiku, 55) | 55 × $0.0032 + 41 judge × $0.0022 ≈ $0.27 |
| A warm | ~$0 (every call, judge included, should be a cache hit) |
| repeat probes | ~10 misses × $0.003 ≈ $0.03 |
| τ sweep (2 × Haiku) | ≈ $0.54 |
| B (Sonnet, 55) | 55 × $0.0065 + judge ≈ $0.45 |
| C (Opus, 55) | 55 × $0.0135 + judge ≈ $0.83 (generation $0.74) |
| **Total still to spend** | **≈ $2.12**; spent so far $0.16; projected day total **≈ $2.3** |

- **Opus stays at `effort: medium`.** $0.74 is under the spec's $1.20
  allowance. That rule was set before any results, so medium isn't
  raised to high just because there's room: changing it now would be
  tuning after seeing numbers.
- **The τ sweep stays in.** The projected total is well under the $3.50
  guard.
- The no-retrieval questions are cheaper than golden ones (2 calls, no
  retrieval), so these projections are slightly conservative.

### Milestone 9: Haiku runs (A cold, A warm, repeat probes, τ sweep)

**Run A cold** (`runs/20260926-182305_haiku_A`, τ = 0.10):
- Task success **50/55 (0.909)**. Gate 55/55. not_in_corpus recall 4/4,
  with 1 false decline (q013). Citation hit 40/41 answerable. Version
  checks 4/4. 0 leaks. 0 source-line violations. Direct answers 10/10
  with no `$`.
- Cost per interaction: mean **$0.00285**, p95 $0.0044, max $0.0049.
  Latency p50 5.2 s, p95 10.3 s (LLM mean 3.6 s, retrieval mean 1.8 s).
- Rounds: 10 questions × 0 rounds, 40 × 1, 5 × 3. Cost by purpose: gate
  $0.052, generate $0.089, rewrite $0.010, direct $0.006. The **gate is
  ~34% of interaction spend**.
- Run spend $0.243, of which judge $0.086.

**Run A warm** (same namespace): 117/117 LLM calls were cache hits, $0.
Latency p50 **1.7 s** (it's all retrieval now; LLM mean 2 ms), against
5.2 s cold. Same 50/55 task success: the cached answers replayed exactly.

**Repeat-traffic probes** (namespace A, $0.030): 8/8 surface variants
hit, 5/5 paraphrases missed, 3/3 tenant swaps missed, 2/2 corpus changes
missed, after one fix to the probe scoring:
- r014 (q038 asked as the business tenant) first scored as "partial".
  Its **gate call missed**, correctly, since tenant is part of the key.
  But its three rounds all retrieved the same single business-fee chunk,
  so rounds 2-3 sent the generator an identical request and got round
  1's cached decline for $0.
- Those are **within-question** repeats, not cross-question
  equivalence. Probes are now scored on the first (gate) call, and
  within-question hits are reported separately. Re-scored from the run's
  own records (`run_eval.py --regrade-probes`), with no re-run.
- The trace also showed a correct behaviour: a *business* member asking
  about a *personal* checking account's wire fee was declined in all
  three rounds ("business account wire fees … a different product").
- Side finding for the report: the exact-match cache makes decision 12's
  retries free whenever a rewrite retrieves the same evidence again.

**τ sweep** (Haiku, fresh namespaces):

| τ_keep | Task success | Judge c / p / i | False declines | Rounds 0/1/2/3 | Cost / interaction | Rewrite helped | Rescued after decline |
|---|---|---|---|---|---|---|---|
| 0.05 | 51/55 | 37 / 2 / 2 | 0 | 10/39/2/4 | $0.00299 | 2 | 1 (q024) |
| **0.10** (run A) | 50/55 | 36 / 1 / 3 | 1 (q013) | 10/40/0/5 | $0.00285 | 0 | 0 |
| 0.30 | 51/55 | 37 / 2 / 2 | 0 | 10/40/1/4 | $0.00274 | 1 | 0 |

- **The difference is noise, not τ.** Eight questions failed in at least
  one run. Only **q034 failed in all three**. The others moved between
  runs:

  | Question | τ 0.10 | τ 0.05 | τ 0.30 |
  |---|---|---|---|
  | q012 | ok | ok | incorrect |
  | q013 | not_in_corpus | ok | ok |
  | q015 | partial | ok | ok |
  | q022 | incorrect | ok | ok |
  | q033 | ok | partial | partial |
  | q034 | incorrect | incorrect | incorrect |
  | q035 | incorrect | incorrect | ok |
  | q042 | ok | partial | partial |

  The cause is non-determinism. The gate writes a different search query
  each fresh run (q013: three different first queries across the three
  runs), and the generator phrases answers differently. **τ stays at
  0.10**: a one-question difference is inside run-to-run noise at n=55.
  **The same caution applies to the model comparison:** differences of
  1-2 questions (2-4 points) aren't evidence.
- **Decision 12 exercised live:** q024 at τ = 0.05. Round 1's answer
  cited nothing valid (`ungrounded`), was blocked, and was rewritten
  ("how long does auto loan approval take"). Round 2 answered. Rewrites
  after a low-relevance round also rescued q013 (τ 0.05) and q040
  (τ 0.30).

**Failures in run A, read by hand:**

| Question | What went wrong | Whose fault |
|---|---|---|
| q013 formal complaint response time | 3 rounds all below τ; the queries never reached the complaint passage (in the τ 0.05/0.30 runs, different wording found it) | retrieval / query wording |
| q015 closing balance | core fact correct; judge said "partial" for *extra* correct alternatives | **judge too strict** (its rules say extra detail is fine) |
| q022 30-year mortgage | swapped the labels: "6.375% APR (6.521%)" instead of rate 6.375%, APR 6.521% | generator (genuine) |
| q034 lost card + fraud | a detailed answer that omits "replacement arrives in 7-10 business days" (that fact is in another chunk: multi-chunk) | generator/retrieval coverage; **judge said "incorrect" for an omission, where its rules say "partial"** |
| q035 consumer loan late | says late "by the due date", missing the 15-day grace period | generator (genuine) |

→ **Judge calibration (milestone 10 pause) must look at**
**omission → "incorrect"** (should be partial) and **extra detail →
"partial"** (should be correct).

Spend after milestone 9: **$0.896** (ledger).

### Milestone 10: Sonnet (B) and Opus (C) cold runs

Runs: `runs/20260928-075104_sonnet_B`, `runs/20260928-075936_opus_C`.
The comparison is `runs/compare_20260928-082444.md`.

| Generator | Task success | Judge c/p/i | $/interaction | $ p95 | $/success | Latency p50 / p95 | Out tokens / generate | Run spend (incl. judge) |
|---|---|---|---|---|---|---|---|---|
| Haiku 4.5 | 50/55 | 36/1/3 | $0.00285 | $0.0044 | $0.00314 | 5.2 / 10.3 s | 139 | $0.243 |
| Sonnet 5 (no thinking) | 50/55 | 36/2/2 | $0.00613 | $0.0107 | $0.00674 | 6.8 / 11.9 s | 222 | $0.427 |
| Opus 5 (adaptive, medium) | **53/55** | 39/1/1 | $0.01212 | $0.0232 | $0.01257 | 8.1 / 12.9 s | 304 | $0.762 |

- Every model: gate 55/55, not_in_corpus 4/4, direct 10/10, 0 leaks, 0
  source-line violations, 0 max_tokens hits, 0 fallbacks.
- **Remember the noise band (milestone 9):** the same Haiku setup scored
  50-51/55 across three runs. Opus's +3 is at the edge of that band, not
  far outside it. It is consistent with Opus fixing the multi-chunk
  "read carefully" failures (q015, q035 correct; q034 partial instead of
  incorrect), but n=55 in one run can't prove it.
- **Questions that failed on at least one model:**

  | Question | Haiku | Sonnet | Opus |
  |---|---|---|---|
  | q013 | not_in_corpus | ok | ok |
  | q015 | partial | partial | ok |
  | q020 | ok | partial | ok |
  | q022 | incorrect | ok | ok |
  | q024 | ok | not_in_corpus | ok |
  | q033 | ok | ok | incorrect |
  | q034 | incorrect | incorrect | partial |
  | q035 | incorrect | incorrect | ok |

  **q034 is the only question no model got fully right.** The fact it
  needs ("replacement arrives in 7-10 business days") sits in a
  different chunk. It's a retrieval-coverage problem more than a model
  problem.
- **Provider prompt caching kicked in on Opus only:**
  - Opus: 1,367 cache-write and 41,271 cache-read tokens. The generate
    and direct-answer system prompts (~850 / ~515 tokens) are above
    Opus 5's 512-token minimum.
  - Sonnet (1,024 minimum) and Haiku (4,096 minimum): 0.
  - Saving on Opus ≈ 41,271 × ($5.00 − $0.50)/M ≈ **$0.19 over the
    run**, ~25% of Opus's generate+direct spend. Without it, Opus would
    be about $0.0155/interaction.
  - This is the "priced at the discounted cache-read rate, not free"
    case the lab describes, and the wrapper priced it that way.
  - Table caveat: "generate input tokens" counts only *uncached* input,
    which is why Opus shows 998 against Sonnet's 1,870.
- **Opus q028 fails `version_quoted` (0.75 on Opus).** The answer says
  "Under the Overdraft Policy v3.0 … Note this fee was reduced from $32
  under the previous version 2.0." That's accurate: it comes from v3's
  own "9. Policy Review" section. But decision 14's rule ("names version
  3, never version 2") counts it as a fail. **The rule isn't changed
  after seeing results.** The report shows both the rule's result and a
  human reading ("correct, and it labels v2 as the previous version").
  A better rule would reject v2 only when it's presented as current.
- **Sonnet q024: a principled false decline.**
  - It declined all 3 rounds because "the chart … is a model-generated
    figure caption, not verified source content".
  - That's the Day 6 caption label (`[Figure caption, model-generated …]`)
    doing its job: Sonnet treated generated text as untrustworthy
    evidence.
  - Graded as a false decline. It's a policy question for Harbor:
    *should* the agent answer from model-generated captions?
- **Opus q033: an output artifact.**
  - The answer contains broken fragments ("loan \ninch it must be
    paid", "\nsic two forms of ID") where dashes belonged.
  - They're in Opus's raw structured-output text; the source chunk is
    clean.
  - It's the only occurrence across all three runs (a scan for the
    pattern found 0 in Haiku and Sonnet).
  - The judge marked q033 incorrect for a different reason: it says the
    answer "cannot confirm" the 30-day review period.
- **Gate share of interaction cost:** Haiku ~36%, Sonnet ~19%, Opus ~11%.
- Spend after milestone 10: **$2.0845** (ledger).

### Milestone 11: comparison and replay proof (no spend)

- `compare.py` builds the table from the run folders only (JSON + MD in
  `runs/compare_*`).
- **Replay proof:** `run_eval.py --generator opus --namespace C
  --replay-of runs/20260928-075936_opus_C` was run with
  `ANTHROPIC_API_KEY` removed. Result: **IDENTICAL**. All stable fields,
  every citation, every task_success and judge verdict match; $0 spent.
  Any reported run can be reproduced from the committed `cache/llm/`.

### Milestone 10 pause: judge calibration → judge_v2 (decision 15)

**Who calibrated:** the user said "continue" without choosing a
calibration option. Using best judgement, the 30-case sheet
(`artifacts/judge_calibration.md`, 10 per model, every non-"correct"
verdict first) was graded by **Claude as an independent second grader**,
against `judge_v1.md`'s written rules, *before* looking at the judge's
verdicts. **This is one model checking another, not a human check.** The
sheet has blank "Human verdict" lines for a human pass. Results are in
`runs/judge_calibration.json`.

**judge_v1 vs second grader: 24/30.** All 20 of the judge's "correct"
verdicts agreed. All 6 disagreements were the judge **breaking its own
written rules**, in two systematic patterns:

| Pattern | Cases | v1 said | Rule says |
|---|---|---|---|
| A missing fact, nothing contradicted | Haiku q034, Sonnet q034, Sonnet q035, Opus q033 | incorrect | partial |
| Extra true detail the reference doesn't mention | Haiku q015, Sonnet q015 | partial | correct |

**Decision 15: fix the judge (v1 → v2) and re-grade every reported run.**
- Why this isn't tuning to the test: the judge is the *measuring
  instrument*, not the system under test. v2 says the same thing as v1,
  but as an explicit procedure: check contradiction first → then
  omission → otherwise correct. It adds "extra detail is never a reason
  to lower the verdict" and "a number on the wrong label is a
  contradiction".
- The agent's answers were **not** re-generated. `src/regrade.py`
  re-judged the fixed answers. v1 grades are kept as
  `grades_judge_v1.jsonl` and `quality_judge_v1` in each summary. The
  judge calls are recorded in `runs/<run>__judge_v2/`.
- Cost: **$0.49** for 6 runs (A, B, C, the τ sweep and A warm; the warm
  run was all cache hits).

**Effect on task success:**

| Run | judge_v1 | judge_v2 | Verdicts that changed |
|---|---|---|---|
| A Haiku | 50/55 | **51/55** | q015 partial→correct, q034 incorrect→partial |
| B Sonnet | 50/55 | **52/55** | q015, q020 partial→correct; q034, q035 incorrect→partial |
| C Opus | 53/55 | **53/55** | q033 incorrect→partial |
| τ 0.05 | 51 | 51 | q022 correct→incorrect, q034 incorrect→partial, q042 partial→correct |
| τ 0.30 | 51 | 51 | same three as τ 0.05 |

**judge_v2 vs second grader on the same 30 cases: 29/30.**
- The one difference is Sonnet q020. The question asks for the *lowest*
  APR; the answer gives 4.49% as the base rate and 4.14% after
  discounts. v2 said correct, the second grader said partial. That's a
  genuinely ambiguous question.
- **Caveat: v2 was written after seeing these 30 cases, so 29/30
  overstates it.**
- Small held-out check (verdict changes in the sweep runs, not in the
  30):
  - q042 ×2, partial→correct: agree.
  - q022 ×2, correct→incorrect, on an answer that reads "6.375% APR
    6.521%": ambiguous formatting. v2 applies its wrong-label rule
    strictly. Borderline.

**Reading the headline after the fix:**

| | Haiku | Sonnet | Opus |
|---|---|---|---|
| Task success (judge_v2) | 51 | 52 | 53 |
| Cost / interaction | $0.0029 | $0.0061 | $0.0121 |

The quality spread is now 2 questions, **inside the 50-51 run-to-run
band** seen on Haiku alone. On this eval, the three generators can't be
told apart on quality. Cost differs ~4× and latency ~1.6× at the median.

Spend after re-grading: **$2.5754** (ledger). No further API calls are
planned; the report and deck are built from recorded runs.

### Milestones 12-14: write-ups (no spend)

- `artifacts/gate_adaptation_decision.md`: verdict **prompt, for now**,
  with the measured gate numbers (165/165, $0.00095, 1.33 s p50) and
  thresholds for switching.
- `artifacts/cost_latency_comparison_report.md`: the assignment
  artifact. Every figure comes from `runs/compare_20260928-105701.*` or
  the run folders. The spend breakdown and ratios were re-checked
  against the ledger, and two typed figures were corrected ($0.18 →
  $0.16; +57% → +56%).
- `artifacts/high_level_deck.md`: 8 slides.
- One more finding while writing the worked example (q024, τ 0.05): the
  round-1 "ungrounded" block happened because Haiku wrapped the chunk
  ID in square brackets. It was a formatting slip, not a hallucination.
  Listed as a known gap (normalise IDs before the guard); not changed
  after the results were recorded.

**Day total: $2.5754** of the $4.00 limit (guard $3.50 never reached).

### Human calibration pass (added by the user to `artifacts/judge_calibration.md`)

The user graded all 30 cases on the Human verdict lines. "Correcy" on
Sonnet #1 was read as "correct". Everything is recorded in
`runs/judge_calibration.json` (fields `human`, `human_reason`).

| Agreement with the human | 3-level | Correct vs not correct (drives task success) |
|---|---|---|
| judge_v1 | 28/30 | 28/30 |
| **judge_v2** (reported) | 25/30 | **29/30** |
| Claude second grader | 26/30 | 30/30 |

- **The headline metric is human-validated.** v2 matches the human on
  correct vs not correct 29/30. The human confirmed v2's key fix: q015
  on Haiku and Sonnet is correct, because extra true detail isn't
  penalised.
- **The one headline disagreement is Sonnet q020.** Human: partial
  ("includes required fact but with information that contradicts the
  reference"); v2: correct. Adjusted to the human on the checked cases,
  task success is Haiku 51, **Sonnet 51**, Opus 53. That's still within
  noise, so the conclusion is unchanged.
- **On partial vs incorrect, the human agrees with v1, not v2.** The
  human graded a missing required fact as *incorrect* in 4 of 5
  omission cases (Haiku q034, Sonnet q034, Sonnet q035, Opus q033) and
  as *partial* once (Opus q034). v2 and the Claude second grader both
  followed the rubric text literally ("an omission is partial"). So
  **decision 15 moved the judge away from the human on this
  distinction**, while moving it towards the human on the one that
  matters for task success.
- **Decision: no v3 re-grade.** Relabelling partial→incorrect changes
  no task-success number and would cost ~$0.45. The report says the
  partial/incorrect split reflects the written rubric, not the human's
  standard, and that the rubric's handling of omissions needs Harbor's
  decision.

### Correction: output artifacts are in 8 answers, not 1

The earlier scan (milestone 10) only looked for the "\ninch"-style
fragments, and found q033. A wider scan (literal `\uXXXX` escapes, stray
quotes) finds **8 answers**:

| Model | Answers | Artifact |
|---|---|---|
| Opus | q001, q008, q009, q031, q032 | a literal `—` where an em dash belonged |
| Opus | q014 | a stray `"` |
| Opus | q033 | garbled "\ninch" / "\nsic" fragments |
| Sonnet | n002 | a literal `—` |
| Haiku | — | none |

The source chunks are clean, so it's in the models' structured-output
text, and a member would see it. It was found while rereading the
calibration cases (Opus #3 q001, Opus #6 q014). The report and deck are
corrected. Fix idea: normalise escape sequences before display, and
check whether the pinned SDK is involved.
