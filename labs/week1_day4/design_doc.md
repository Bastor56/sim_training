# Customer Service Agent — CRM Integration
Design Document — Proof of Concept

## Status and scope

This agent answers customer account questions (balances, transactions,
cards, profile info) by querying the bank's CRM. Production CRM
credentials were not available for this phase, so the agent was built
and validated against a simulator that implements the CRM's documented
API contract exactly — its own independent HTTP service, not code
embedded in the agent. Section 6 lists where that substitution is an
assumption still to be confirmed against the real system.

## 1. Architecture

Four layers, data flowing one way per customer turn:

1. **Conversation** — session state and turn history. Passive: no model
   or CRM calls here.
2. **Decision** — one model call per turn: does this need account data,
   and if so, which CRM operation answers it — or is it a fact already
   retrieved and stated earlier this same conversation, answerable by
   recalling that instead of calling the CRM again?
3. **Tool** — the only layer that talks to the CRM. Owns timeouts, retry,
   and translates whatever the CRM actually returns into one of three
   outcomes: *found*, *not found*, *unavailable*.
4. **Response** — composes what the customer sees, from the decision and
   (if applicable) the tool outcome.

There is no loop at the architecture level — each turn is decision →
(tool) → response, once. The only retry anywhere is inside the tool
layer, on a single CRM call, invisible to the rest of the agent.

**The boundary around the tool layer is deliberate and load-bearing:**
every other layer reasons only in terms of *found / not found /
unavailable*, never in terms of HTTP status codes or CRM-specific
response shapes. That's what makes pointing the agent at the production
CRM a configuration change — a base URL and credentials — rather than a
rewrite of decision or response logic.

Orchestration uses direct graph primitives, not a pre-built agent
construct, so the exact instructions given to the model are reviewable
in application code rather than assembled implicitly by a framework
default — important in a regulated environment. Retry is implemented in
the tool layer itself, not delegated to the orchestration layer, so it
stays scoped to exactly the CRM call and nothing else.

## 2. Tool contract

| Operation | Request | Returns |
|---|---|---|
| Get customer profile | customer ID | name, email, customer-since date |
| List customer's accounts | customer ID | account ID, type, status per account |
| Get account detail | account ID | type, balance, status |
| List account transactions | account ID, limit | recent transactions |
| List account cards | account ID | card ID, last four, status |

Every response is validated against a schema the agent owns itself — a
`200` status is not treated as proof the body is well-formed.

| Outcome | Meaning |
|---|---|
| **Found** | Validated response. An empty result (e.g. no transactions) is still found — not the same as not found. |
| **Not found** | Record doesn't exist. Not retried. |
| **Unavailable** | Unreachable, timed out, server error, or malformed body. Retried up to 3 times with exponential backoff, then reported as unavailable. |

## 3. Conversation state

```
Session: session_id, customer_id, turns: [Turn, ...]
Turn: customer_message, account_referenced, tool_used, crm_result, agent_reply
```

One session per identified customer, state persisted across turns, so
referential prompts resolve against what has previously been discussed.
That resolution is deterministic, not model-guessed: the
decision step classifies *how* an account was referenced (named
explicitly, a pronoun for what was just discussed, or "the other one"),
and a separate function matches that against the customer's known
accounts and the conversation so far. If the match is ambiguous, the
agent asks a clarifying question rather than guessing — the model is
never in a position to invent an account identifier.

The same discipline extends to *whether* the CRM needs to be called at
all. The decision step can also classify a turn as asking to be reminded
of something already retrieved this session (e.g. "what did you say the
balance was?"), naming the same CRM operation and account reference a
fresh lookup would use. A second deterministic function matches that
against turn history — by which operation produced the data and which
account it concerned — and replays the cached result if it finds one.
A request that looks like a recall but doesn't actually match anything
already retrieved falls back to an ordinary CRM call rather than
answering from a guess: recalling is a data-driven match against what
actually happened this session, never a model's guess about what it
probably already said.

## 4. Failure handling policy

| Condition | Signal | Outcome | Retried | Customer sees |
|---|---|---|---|---|
| Unknown customer/account | `404` | Not found | No | Specific "couldn't find that," offer to escalate |
| Server error | `5xx` | Unavailable | Yes (3x) | Generic "having trouble reaching our systems," offer to escalate |
| Timeout | exceeds configured timeout | Unavailable | Yes | Same generic message |
| Malformed response | `200`, invalid body | Unavailable | No | Same generic message |
| Ambiguous account reference | n/a — not a CRM failure | — | — | Clarifying question, never a guess |

The agent never fabricates account data — when data isn't available, for
any reason, the reply says so and offers a path to a human. Internal
failure detail (status code, exception) is logged for support staff but
never shown to the customer; every failure and clarifying reply is
generated by fixed, reviewable logic, not the model. The model only
generates free-form text when a turn needs no account data at all (a
greeting), and is explicitly instructed never to state an account fact
in that case.

## 5. Validation and known risks

Validated against the simulator across multi-turn conversations and each
failure condition in Section 4, triggered on demand. Two open items from
that validation:

- **Decision step occasionally returned an unusable model response** —
  under sampling settings chosen for reasoning variation, the model can
  spend its output budget on internal reasoning before its answer,
  leaving nothing for the output itself. Budget was increased, which
  reduces but doesn't eliminate this; when it recurs, the agent treats it
  as a genuine, logged failure rather than retrying silently.
- **The orchestration layer's session-persistence mechanism logs a
  compatibility warning** for the custom data types this agent stores in
  session state. Not currently a functional problem on the pinned
  library version, but a forward-compatibility gap to close before
  production hardening.

## 6. Assumptions to confirm before production

- **No authentication** on the simulator — production needs an API
  key/OAuth token per request and a refresh path.
- **No pagination** — transaction lookups return everything up to a flat
  limit; production likely needs cursor-based paging.
- **No rate-limit awareness** — every server error retries on the same
  fixed curve; production rate-limiting typically specifies its own
  required wait time.
- **No eventual consistency** — the simulator is always immediately
  consistent; a production CRM behind caching/replication may not be.
- **Assumed reliability differences between operations** (e.g. identity
  lookups vs. account detail) were a simplification for this phase, not
  confirmed against the real system.
- **Customer's account list is fetched once per session**, not
  refreshed — an account opened or closed mid-conversation wouldn't be
  reflected until the next session.
- **A recalled fact (e.g. a balance restated instead of re-fetched) is
  only as fresh as when it was first retrieved this session** — the same
  staleness assumption already made for the account list above, extended
  to individual facts recalled later in the same conversation.
- **Exactly one CRM call per turn** — a question needing two calls in one
  turn (e.g. comparing two accounts directly) is out of scope for the
  current architecture.
- **Customer identity is provided to the session, not authenticated by
  it** — production needs a real login/session-auth flow.

These are deliberate scope boundaries for this phase, not defects —
listed here so they're scoped into (or knowingly deferred from) the next
phase rather than discovered by surprise.
