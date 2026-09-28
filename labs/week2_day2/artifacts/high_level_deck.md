# FDE Xlerate - Week 2, Day 2
High-level deck: agentic RAG with cost per interaction, and three models compared (Harbor Credit Union)

## Slide 1: Title / Framing
- **Client: Harbor Credit Union.** 180,000 members, a 40-person contact centre, and a hard rule: every
  answer must be traceable to its source.
- Day 1 built and measured **retrieval** over Harbor's documents (R@5 = 0.90). **Today turns it into an
  agent that answers**, and puts a price on every answer.
- The FDE standard: improving quality isn't finished until you can say **what one member question
  costs and how long it takes**. That's the number a client's finance review asks for.

## Slide 2: The Problem
- **Static RAG fails in two ways:**
  - it retrieves on every message, even "Hi there!";
  - it confidently summarises whatever comes back, even an irrelevant top-5.
- **Agentic RAG fixes both, but makes cost variable:**
  - the agent decides whether to retrieve;
  - it checks what it got;
  - it rewrites its query and tries again.

  Each extra step is another model call, so cost per question has no fixed size, and without a cap
  it has no upper bound.
- **Harbor's constraints make it harder:**
  - name the source of every answer;
  - quote the policy version in force;
  - never leak a restricted or other-tenant document;
  - say "not in our documents" rather than guess.
- **Today's deliverables:**
  - the agent;
  - one instrumentation wrapper that can't be bypassed;
  - cost per interaction;
  - a cache;
  - a three-model comparison.

## Slide 3: High-Level Flow
```
member question ──▶ GATE (Haiku) ── no documents needed ──▶ direct answer
   (1 ID per          │  needs Harbor's documents                 + "general information" source
    question)         ▼  (gate writes the search query)
                 RETRIEVE: Day 1 hybrid search + rerank ◀──────────────┐
                      ▼                                                │
                 VALIDATE: rerank score ≥ 0.10?  ──── no ──────────────┤ REWRITE the query,
                      │ yes                                            │ told why the round failed
                      ▼                                                │ (max 3 rounds, in code)
                 GENERATE: grounded answer ─── declines a near miss ───┘
                      │     or blocked citation
                      ▼                                   after round 3 ──▶ "not in Harbor's documents"
                 reply + source line built by code: title, version, effective date
```
- Every step, and the reason for every gate decision, is written to a per-question trace.

## Slide 4: Architecture: One Door to the Model
```
agent node ──▶ llm.call() ──▶ record (always, even on error) ──▶ exact-match cache ──hit──▶ $0 (still recorded)
                                                                       │ miss
                                                                       ▼
                                             spend guard ($3.50) ──▶ Anthropic API ──▶ priced from pricing.json
```
- **One file owns the only API client.** A test fails if any other code imports the SDK.
- **Every record carries:** model, tokens (thinking included), cache tokens, latency, cost, purpose,
  and the question's correlation ID. That gives cost per interaction as a plain sum.
- **Two-layer relevance check:**
  - the reranker threshold catches off-topic results for free;
  - the generator catches near misses: "the passage is about *auto* loans, not RV loans".
- **Cache rule:** share an answer only when the model, prompt, full evidence, tenant, access and corpus
  version are all identical. A semantic cache would mix up "retail vs business fee" and "v2 vs v3".

## Slide 5: Tech Stack
- **Agent:** LangGraph `StateGraph` (hand-written nodes, prompts as versioned files), Python 3.12, uv.
- **Retrieval (Day 1, reused unchanged):** Chroma + BM25 hybrid search, bge-small embeddings,
  bge-reranker cross-encoder, all local.
- **Models:**
  - gate and rewrite: Claude Haiku 4.5;
  - generator candidates: **Claude Haiku 4.5 / Sonnet 5 / Opus 5** (Opus: adaptive thinking,
    effort = medium, max_tokens = 4,000);
  - judge: Sonnet 5.
- **Instrumentation:** the wrapper, a `contextvars` correlation ID, JSONL call records, a committed
  spend ledger with a guard, and `pricing.json` pinned from the live price page.
- **Cache:** an exact-match local cache (committed), plus Anthropic prompt caching, which engaged on
  Opus only (512-token minimum).
- **Quality:** Day 1's 45-question golden set + 10 new "don't retrieve" questions. Deterministic checks,
  plus an LLM judge calibrated against a second grader and a human reviewer (30 cases).
- **Thinking budget, stated plainly:** current models reject `budget_tokens` (HTTP 400). Opus's budget =
  effort level + a max_tokens ceiling.

## Slide 6: Results: Three Models, Same Task
| | Haiku 4.5 | Sonnet 5 | Opus 5 (reasoning) |
|---|---|---|---|
| Task success (of 55) | 51 | 52 | 53 |
| **$ per member question** | **$0.0029** | **$0.0061** | **$0.0121** |
| $ p95 | $0.0044 | $0.0107 | $0.0232 |
| Latency p50 / p95 | 5.2 / 10.3 s | 6.8 / 11.9 s | 8.1 / 12.9 s |
| Output tokens per answer | 139 | 222 | 304 |
- **The quality gap (2 questions) is inside run-to-run noise.** The same Haiku setup scored 50-51 across
  three runs.
- **Cost and latency gaps are real:** Opus is **4.2× the cost** and **+2.9 s** at the median.
- Opus's gains came from multi-part questions (reading more of the evidence), with light thinking at
  medium effort.
- **Every model:**
  - gate 55/55;
  - 4/4 unanswerable or restricted questions ended "not in the corpus";
  - 0 leaks;
  - every reply names its source.

## Slide 7: Cache, Cost per Interaction, and the Gate Decision
- **Cache:**
  - warm rerun: 100% hits, **$0**, latency p50 **1.7 s** vs 5.2 s cold;
  - probes: case/spacing variants 8/8 hit; paraphrases 5/5, other tenant 3/3 and new corpus 2/2 miss,
    all as designed.
- **Where Haiku's $0.0029 goes:** the gate ~36%, the answer ~57%, rewrites ~6%. The worst case per
  question is bounded: 1 gate + 2 rewrites + 3 answer attempts.
- **Scale (assumption: 5,000 questions/day):** ~$430 (Haiku), ~$920 (Sonnet), ~$1,820 (Opus) per month.
- **Gate adaptation decision: prompt, for now.**
  - It's 165/165 accurate at $0.00095 and 1.3 s.
  - It also *writes the search query*. That rewording is what makes paraphrases retrievable (0.33 vs
    0.02 relevance), and a distilled classifier can't do it.
  - **Revisit** when real-traffic errors pass ~2% (add a labelled-example bank), or when volume passes
    ~35k/day or a latency target rules out the gate (distil it).
- **Recommendation:** Haiku 4.5 as the default generator. Test Opus only on multi-part questions, using
  a larger evaluation.

## Slide 8: Known Gaps / What's Next
- **Evaluation:**
  - 55 questions × one run per model is too small to separate the models on quality. Next: a larger,
    harder set with repeated runs.
  - Judge checked by a human on 30 cases: it matches on correct vs not (29/30), but the human counts a
    missing fact as incorrect where the rubric says partial. Harbor should decide which.
- **Small fixes found:**
  - the citation guard rejects correct IDs wrapped in brackets;
  - the version rule fails correct "the previous version 2.0" history;
  - 8 answers (7 Opus, 1 Sonnet) show text glitches, e.g. a literal `\u2014` where a dash belonged.
- **Retrieval gap:** q034's "replacement in 7-10 business days" sits in a different chunk. No model
  found it.
- **Policy questions for Harbor:**
  - may answers rely on model-generated chart captions? (Sonnet refused to);
  - vendor approval for sending questions and scrubbed evidence to the Claude API.
- **This week:** the router (vector / graph / SQL / MCP). When member memory arrives, member context
  must join the cache key or bypass the cache.
