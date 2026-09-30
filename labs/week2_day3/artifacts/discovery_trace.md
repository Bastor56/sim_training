# Discovery trace: the agent adapts to a new server tool with no agent change

**Harbor Credit Union, Week 2 Day 3.** Evidence for R2: "the client agent
must discover the tool list at runtime and adapt to it: adding a tool on
the server must require no change to the agent." Run on 2026-09-29 against
the live stack (mock CRM, local Postgres, harbor-mcp, the agent), member
`M-1001` (Maria Chen), caller `member_assistant`, `--today 2026-09-28`.
Sources: `runs/adhoc/` (`trace.jsonl`, `calls.jsonl`, `discovery.jsonl`),
the server's audit log.

## The claim, in one table

| | Before | After |
|---|---|---|
| Agent fingerprint (`scripts/agent_fingerprint.py`: SHA-256 over `agent/*.py` + `prompts/*.md`, 23 files) | `7fd25b2d8f81ede0` | **`7fd25b2d8f81ede0`** (identical) |
| Server version | 0.1.0 | 0.2.0 |
| Tools advertised (`tools/list`) | 6 | 7 (+ `get_card_limits`) |
| Tool-list hash (what the model is shown) | `f5e87c29c6eea09e` | `7fd22ec198fa2fa7` |
| "What's my daily ATM withdrawal limit on my debit card?" | `retrieve` → **$500** (Harbor's standard, from the Debit Card Limits document) | `use_tool` → **$800.00** (this card's own limit, from the CRM) |
| "What's the daily purchase limit on my card?" | `use_tool` → dead end: "I don't have access to the daily purchase limit" | `use_tool` → **$5000.00** (this card's own limit) |

A fingerprint of the files, rather than a git commit, because the lab is
uncommitted while it's being built; a file hash also covers uncommitted
edits.

## What changed, and where

**Only the server side:**

| File | Change |
|---|---|
| `backends/mock_crm/{schemas,fixtures,app}.py`, `contract.md` | `GET /cards/{card_id}/limits`; CARD-4001 has raised limits ($800 / $5,000) so the answer's source is visible |
| `mcp_server/backends.py` | `CRMClient.get_card_limits` |
| `mcp_server/tools.py` | the `get_card_limits` tool, with a routing-grade description |
| `mcp_server/server.py` | `SERVER_VERSION = "0.2.0"` |
| `mcp_server/permissions.py` | **one line: the grant** (see "Deny by default") |
| `mcp_server/TOOL_MANIFEST.md` | the tool's contract; changelog line for 0.2.0 |

**Nothing in `agent/` or `prompts/`.** `tests/test_no_bypass.py` also
proves no tool name is written into agent code or prompts: it read the new
name from the permission map and found it nowhere in the agent.

## Deny by default: the one server-side policy change (known gap 4)

The tool was added and the server moved to 0.2.0 **before** it was
granted. At that point (in-process harness, same code):

```
advertised: 0.2.0 ['freeze_card', 'get_account', 'get_card_limits', 'get_member', 'list_cards', ...]
call before grant: refused -32003 forbidden: member_assistant may not call get_card_limits
audit: [('get_card_limits', 'denied', 'forbidden')]
CRM touched: []
```

So "no agent change" is true, and "no change at all" is not: someone at
Harbor has to decide who may use a new tool. That's the intended design
(a tool nobody granted can't be used by anybody), and it's the answer to
the security reviewer's "what stops a new tool being used before it's
reviewed?".

## Before: server 0.1.0

```
DISCOVERY harbor-mcp 0.1.0 at http://127.0.0.1:8200/mcp: 6 tools, hash f5e87c29c6eea09e
          freeze_card, get_account, get_member, list_cards, list_member_accounts, list_transactions

Q: What's my daily ATM withdrawal limit on my debit card?   [adhoc/0012]
GATE     retrieve: The member asks about a Harbor debit card limit that is the same for all members;
         this is a policy or product specification, not specific to their own card or account records.
ROUND 1  query: "debit card daily ATM withdrawal limit"
   kept 1.000  Debit Card Limits and Controls
   ...
REPLY    Your daily ATM withdrawal limit on your debit card is $500, under the Debit Card Limits and
         Controls policy effective 2026-02-02. However, if you have a Premier Checking account, you may
         have a higher limit based on your relationship with Harbor. You can check your current limits
         in the app under Card Controls — Limits.
         Source: Debit Card Limits and Controls (effective 2026-02-02), Daily Limits

Q: What's the daily purchase limit on my card?   [adhoc/0013]
GATE     use_tool: The member is asking about their specific card's spending limit, which requires
         checking their card details from their own records.
TOOL 1   list_cards({"member_id": "M-1001"}) -> ok   records: CARD-4001
OUTCOME  records_cannot_answer
REPLY    I don't have access to the daily purchase limit details for your debit card ending 4471.
         Please contact our member service team and they'll be able to provide this information for you.
         Source: none. Harbor's records were checked: list_cards (checked).
```

## After: server 0.2.0, same agent

```
DISCOVERY harbor-mcp 0.2.0 at http://127.0.0.1:8200/mcp: 7 tools, hash 7fd22ec198fa2fa7
          freeze_card, get_account, get_card_limits, get_member, list_cards, list_member_accounts, list_transactions

Q: What's my daily ATM withdrawal limit on my debit card?   [adhoc/0014]
GATE     use_tool: The member is asking about their own card's ATM withdrawal limit, which is stored in
         the card's current limits in the CRM.
TOOL 1   list_cards({"member_id": "M-1001"}) -> ok          18.5 ms  records: CARD-4001
TOOL 2   get_card_limits({"card_id": "CARD-4001"}) -> ok    13.6 ms  records: CARD-4001
REPLY    Your daily ATM withdrawal limit on your debit card ending 4471 is $800.00.
         Source: Harbor CRM, card limits CARD-4001 (get_card_limits). Retrieved via harbor-mcp 0.2.0
         at 2026-09-29T23:55:28Z.

Q: What's the daily purchase limit on my card?   [adhoc/0015]
GATE     use_tool: The member asks about their own card's daily purchase limit, which requires looking
         up their card's actual limits from their records.
TOOL 1   list_cards({"member_id": "M-1001"}) -> ok           8.6 ms  records: CARD-4001
TOOL 2   get_card_limits({"card_id": "CARD-4001"}) -> ok    11.3 ms  records: CARD-4001
REPLY    Your daily purchase limit on your debit card ending 4471 is $5000.00.
         Source: Harbor CRM, card limits CARD-4001 (get_card_limits). Retrieved via harbor-mcp 0.2.0
         at 2026-09-29T23:55:34Z.
```

Server audit log for the "after" run (one line per `tools/call`):

```json
{"ts": "2026-09-29T23:55:27.584Z", "caller": "member_assistant", "tool": "list_cards", "arguments": {"member_id": "M-1001"}, "decision": "allowed", "outcome": "ok", "server_version": "0.2.0"}
{"ts": "2026-09-29T23:55:28.557Z", "caller": "member_assistant", "tool": "get_card_limits", "arguments": {"card_id": "CARD-4001"}, "decision": "allowed", "outcome": "ok", "server_version": "0.2.0"}
{"ts": "2026-09-29T23:55:33.135Z", "caller": "member_assistant", "tool": "list_cards", "arguments": {"member_id": "M-1001"}, "decision": "allowed", "outcome": "ok", "server_version": "0.2.0"}
{"ts": "2026-09-29T23:55:34.166Z", "caller": "member_assistant", "tool": "get_card_limits", "arguments": {"card_id": "CARD-4001"}, "decision": "allowed", "outcome": "ok", "server_version": "0.2.0"}
```

## How the agent adapted: the mechanism

1. **On connect**, the gateway calls `tools/list` and fingerprints the
   result. The fingerprint changed (`f5e8…` → `7fd2…`), so it's recorded
   in `runs/adhoc/discovery.jsonl` and on every gate trace event.
2. **The gate's prompt** ends with the discovered tools, each with its full
   description, built at runtime. With `get_card_limits` listed ("a card's
   own current daily limits … can differ from Harbor's standard limits"),
   the gate's rule "choose `use_tool` only if a listed tool can provide
   it" now holds for limit questions.
3. **The tool step** passes the discovered input schemas straight to
   Claude's `tools` parameter. The model chained `list_cards` (to get the
   card ID) into `get_card_limits`, as the new tool's description says to.
4. **The gate's cache key includes the tool-list hash**, so no decision
   made against the 0.1.0 list could be replayed under 0.2.0. All four
   gate calls above were cache misses.

## Honest caveats

- **The "before" baseline was taken twice.** The first 0.1.0 run exposed a
  bug in the agent (milestone 6 code): the gate saw only the first line of
  each tool description, and `list_cards`'s first line wraps before "Does
  not return spending limits". The gate then routed limit questions to
  tools that couldn't answer them. The fix (full descriptions) was made
  **before** the baseline fingerprint `7fd25b2d8f81ede0` was taken, and the
  "before" run above is the post-fix one. Findings log, milestone 8.
- **The gate is not consistent on similar wording.** Before 0.2.0, the ATM
  question went to documents but the purchase question went to the tools
  and dead-ended safely ("I don't have access…"; nothing invented). One run
  each; the eval (milestone 10) measures routing over more questions.
- **Formatting:** "$5000.00" without a thousands separator: the model
  copied the record's decimal string exactly, as `generate_from_tools_v2`
  instructs. Correct, if not pretty.
- **Cost:** each limit answer is ~$0.011 (5 LLM calls), vs ~$0.004 for
  the document answer it replaced. The cost of being specific to the member.
