# Adaptation decision: the retrieval gate

**Harbor Credit Union, Week 2 Day 2.** Written decision for one narrow LLM call (lab requirement R7).
Sources: `runs/20260926-182305_haiku_A`, `runs/20260926-185620_haiku_A_tau005`,
`runs/20260926-190245_haiku_A_tau030`; shares on Sonnet/Opus from `runs/20260928-075104_sonnet_B`,
`runs/20260928-075936_opus_C` (gate calls: `calls.jsonl`, `purpose = "gate"`), prices from
`pricing.json` (2026-09-25).

## The call

The gate is the first step for every member question. One Claude Haiku 4.5 call, with prompt
`prompts/gate_v1.md`, does **two jobs**:

1. **Decide** whether answering needs Harbor's documents (`retrieve`) or not (`answer_direct`), and log a
   one-sentence reason (the lab requires the reason on every turn).
2. **Write the first search query.** It turns the member's words into the wording Harbor's documents use
   ("send money to someone at another bank" becomes "outgoing domestic wire transfer").

The second job matters more than it looks. On the first live traces, the reranker scored the Wire Transfer
Policy at **0.13-0.33 against the gate's query, but only 0.003-0.018 against the member's own words**.
Without the gate's rewording, that paraphrase would have failed every round (findings log, milestone 6).

**Measured (165 gate calls, 3 runs × 55 questions):**

| | Value |
|---|---|
| Accuracy | **165/165** (45 retrieve + 10 answer_direct per run, 3 runs, no errors) |
| Cost per call | **$0.00095** mean (p95 $0.00101): ~684 input + ~53 output tokens |
| Latency | **1.33 s** p50, 1.90 s p95 |
| Share of cost per interaction | ~36% on Haiku (35-38% across runs); ~19% on Sonnet 5; ~11% on Opus 5 (runs B, C) |
| Share of latency | ~26% of a Haiku interaction's p50 (1.33 s of 5.2 s) |

## Option 1: prompt (current, chosen)

- **What it is:** the current prompt: rules for retrieve vs answer directly, written before any results.
- **Cost:** $0.00095 per question. At an assumed **5,000 questions/day**, that's about **$143/month** for
  the gate. (The volume is an assumption for scale, not Harbor data.)
- **One-off effort:** done. Changing the boundary means editing a text file, bumping the version and
  re-running the eval (~$0.27 for a Haiku run).
- **Strengths:** it does both jobs (decision + query), gives a readable reason, and has no training data
  to maintain.
- **Risks:** every question goes to an external API. It adds ~1.3 s per question. It hasn't been tested
  on real Harbor traffic (our 55 questions are clean and unambiguous).

## Option 2: RAG over labelled examples

- **What it is:** keep a bank of labelled member messages (message → retrieve / answer_direct). Look up
  the 3-5 most similar with the bge-small embedder we already run, and put them in the gate prompt as
  examples.
- **Cost:** ~200-300 extra input tokens per call (~+35-45% input), about **+$0.0003 per call** on Haiku,
  plus a ~10-50 ms local embedding lookup. Plus building and maintaining the labelled bank.
- **What it would buy:** better accuracy on borderline messages. **There is no headroom to measure on
  this eval: the prompt is already 165/165.** So today it would be cost with no demonstrated benefit.
- **When it becomes the right move:** as the *first* step if real traffic shows gate errors. It's cheap
  to add and keeps both jobs and the reason.

## Option 3: fine-tune / distil into a small classifier

- **What it is:** have the current gate label a large sample of real questions, then train a small
  classifier on those labels (for example logistic regression on bge-small embeddings, which already run
  locally).
- **Cost:**
  - labelling N examples × $0.00095. **2,000 examples ≈ $1.90.**
  - training takes seconds locally;
  - per call it costs **~$0** and takes ~10-20 ms locally, instead of $0.00095 and ~1.3 s;
  - the real cost is engineering time and upkeep: collecting real traffic, reviewing labels, and
    retraining when Harbor adds products or topics shift.
- **What it would lose:**
  - **the search query.** A classifier can decide but can't write the query. Retrieval would fall back
    to the member's own words, which is exactly what failed on paraphrases (see above). Keeping the
    query quality would need a separate LLM call, giving back most of the saving.
  - **the reason.** It would become a probability ("retrieve, p = 0.97"), not a sentence a supervisor
    can check.
- **What it would gain:** the gate's decision stays inside Harbor's environment. That's only a partial
  win, since the generator still sends retrieved text to the API.
- **Can't be done today:** 55 labelled questions are far too few to train on, and none of them are real
  traffic.

## Verdict: prompt, for now

At the measured $0.00095 and 100% accuracy on this eval, the prompt gate is cheap, correct and does both
jobs. RAG-of-examples has no measurable benefit yet. Distillation would throw away the query-writing job,
which the milestone 6 finding shows is load-bearing, to save about a third of a Haiku question's cost, and only ~11-19% of a Sonnet or Opus question's cost: the more expensive the generator, the less the gate matters.

## What would change the verdict

| Trigger | Move to | Why |
|---|---|---|
| Real traffic shows gate errors above ~2% (measured by sampling logged gate reasons) | **RAG over labelled examples** first | Cheapest fix, keeps the query and the reason |
| Volume where gate spend beats the cost of owning a classifier: at an assumed $1,000/month upkeep, when V × 30 × $0.00095 > $1,000, i.e. **V > ~35,000 questions/day** | **Distil the decision**, keep an LLM query rewrite only for `retrieve` | Saves the decision cost. The rewrite could run on fewer questions or a cheaper path. |
| The contact centre sets a latency target the ~1.3 s gate breaks (e.g. total p50 under 3 s) | **Distil the decision** (~10-20 ms), and test whether retrieval on raw questions plus the existing rewrite loop holds quality | Latency, not cost, drives it |
| Harbor rules that member questions may not leave its environment | Not the gate alone: the whole design needs a locally hosted model | Distilling only the gate doesn't meet that rule |

The ~35,000/day threshold depends on the assumed upkeep cost. It's there to show how to reason about it,
not to be quoted to Harbor as fact.
