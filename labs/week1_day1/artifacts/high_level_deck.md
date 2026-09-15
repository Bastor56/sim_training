# FDE Xlerate - Week 1, Day 1
High-level deck: single tool-calling LLM request (FNOL claim intake)

## Slide 1: Title / Framing
- Exercise: prove an LLM can do something useful and repeatable — not just impressive once.
- Use case: first-notice-of-loss (FNOL) intake assistant for a property & casualty insurer.
- Scope: one LLM request, no loop, no agent yet.

## Slide 2: The Problem
- Build the smallest honest version of an LLM-backed feature: structured output + exactly one function call.
- No loop, no agent — the point is to feel where the model is reliable (following a schema) vs. where it isn't (doing it every single time).
- Every failure mode the next four weeks defend against starts here.

## Slide 3: High-Level Flow
- One-way control flow: prompt in → structured object out → function executed. No dynamic branching, no looping tool calls.
- Exactly one decision point in the whole system: on invalid output, retry once with the validation error fed back into the prompt; if the retry also fails, stop and fail clearly.
- That single loop-back arrow is the seed of the hand-built agent loop for tomorrow's lab — an agent is this same shape with the loop-back generalized into "keep going until done," not a new concept.

```
 [1] PROMPT ASSEMBLY        [2] CLIENT              [3] VALIDATE             [4] HANDLER
 system + user prompt  ──▶  Anthropic API     ──▶   Zod schema check   ──▶   execute
 + tool definition          (Claude Sonnet 5)       (response + tool        check_policy_coverage
 (orchestrator)                                      input)                 (Supabase lookup)
                                 ▲                        │
                                 │                        │ valid ─────────────────▶ (to step 4)
                                 │   invalid, attempt 1    │
                                 └── retry: validation ────┘
                                     error appended to
                                     user prompt, call
                                     model again
                                                           │
                                                           │ invalid again, attempt 2
                                                           ▼
                                               FAIL CLEAN: throw ClaimExtractionError
                                               (never pass a half-parsed object downstream)
```

- Two ways out, both explicit: **valid** → claim + tool input hand off to the handler; **invalid twice** → a typed error, never a silent pass-through.
- Everything here is one Anthropic API call per attempt — at most two calls total, never an open-ended loop.

## Slide 4: Architecture
- **Client layer** — owns the Anthropic API call and model config (Claude Sonnet 5); knows nothing about parsing or retries.
- **Schema layer** — single source of truth for "valid": the Zod response contract (loss_date, peril, estimated_severity, coverage_flag) and the `check_policy_coverage` tool definition.
- **Orchestrator** — assembles the three inspectable pieces (system prompt, user prompt, tool definition), owns the one retry loop, logs raw + parsed response on every attempt.
- **Handler layer** — executes the one function the model asked for (Supabase policy lookup); never talks to the model. Policy number is sourced out-of-band (auth session/CRM), never extracted from model output.

## Slide 5: Malformed-Output Handling
- Detect parse/validation failure explicitly (not a crash).
- Retry exactly once, feeding the validation error back into the prompt so the model can self-correct.
- If the retry also fails: fail loudly with a clear error — never silently pass a half-parsed object downstream.
- Demonstrated live via `demo-malformed.ts`.

Forcing this path took more than confusing input — Sonnet 5 stayed schema-compliant even on gibberish claim text, so adversarial prompting alone couldn't reliably trigger it. Instead, the demo swaps in Claude Haiku 4.5 (already benchmarked as unreliable on this exact schema) as the live backing model for one real run. The resulting failure is genuine, not scripted: Haiku wraps valid JSON in markdown fences on the first attempt, drops the text block entirely on the retry, and the real orchestrator throws a clean `ClaimExtractionError`.

## Slide 6: Tech Stack & Key Decisions
- **Claude Sonnet 5** — bounded extraction-plus-one-tool-call task; Opus's extra cost buys nothing, Haiku risks dropping schema fields.
- **TypeScript + Zod** — response contract and tool input/output validated in-app (deliberately not relying on provider-side structured-output enforcement, so validation actually gets exercised).
- **Supabase** — policy lookup via service-role key (server-side only, bypasses RLS by design).
- **pino** — structured logging so raw/parsed responses are queryable after the fact, not just printed.
- **temperature = 1** (only value this model accepts post-deprecation, set explicitly rather than omitted) and **max_tokens = 1024** (headroom for a 5-field object + one tool call, no more).

## Slide 7: Workflow vs. Agent vs. Multi-Agent
- **KYC new account → Workflow.** Fixed sequence with conditional branches; no need for dynamic tool-call decisions. Cheaper, simpler, predictable.
- **AML alert investigation → Agent.** Evidence spread across sources, each finding informs the next step, methods evolve over time — needs dynamic tool use, not a hard-coded playbook.
- **Commercial loan underwriting → Multi-agent.** Specialized sub-processes (financial analysis, credit risk, compliance) split across sub-agents by a coordinator — reduces context/tool-selection noise and improves traceability, at the cost of latency and more failure points.

## Slide 8: Takeaways
- Structured output + single tool call is a workflow, not an agent — no dynamic looping yet.
- The retry-on-invalid-output branch is the only decision point in the system today; it's also the exact seed of the agent loop coming next.
- Reliability boundary observed: the model follows the schema most of the time, but "most of the time" is why the validate → retry → fail-clean path exists at all.
