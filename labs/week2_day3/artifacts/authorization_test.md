# Authorization test: the server says no, and the allow-list isn't what stopped anything

**Harbor Credit Union, Week 2 Day 3.** Evidence for R3 ("authorization must
be enforced server-side per tool call against the caller's identity, and
proven by a call that is correctly refused. Demonstrate that a client-side
allow-list is not enforcement by bypassing one"), R4 (credentials never
accepted from the client) and R5 (every call audited). Run on 2026-09-29
against the live stack: mock CRM, local Postgres, harbor-mcp **0.2.0**.

## Summary

| # | Who | Call | Result | Decided by | Audit line |
|---|---|---|---|---|---|
| 1 | `member_assistant` | `get_account(ACC-2001)` | **ok**, balance $4,210.55 | server: granted | `allowed / ok` |
| 2 | `member_assistant`, **own client, no agent, no allow-list** | `freeze_card(CARD-4001)` | **refused**, `-32003 forbidden` | server: not granted | `denied / forbidden` |
| 3 | `contact_centre` | the same `freeze_card(CARD-4001)` | **ok**, card frozen (CRM reset afterwards) | server: granted | `allowed / ok` |
| 4 | `member_assistant` | `get_account(ACC-2001, db_password="hunter2")` | **refused**, `-32602 invalid arguments` | server: undeclared argument | `denied / invalid_arguments`, value **redacted** |
| 5 | unknown token | connect | **HTTP 401**, no MCP message read | server: authentication | `denied / unauthenticated` ×2, **token not logged** |
| A | the agent **with** its allow-list | "Please freeze my debit card" | model never shown `freeze_card`; tells the member to call the contact centre | client: hid the tool | `list_cards` only |
| B | the agent **without** an allow-list (milestone 7) | the same question | model called `freeze_card`, **server refused** | server | `denied / forbidden` |

**The point of rows 2, A and B:** the allow-list changes what the *model
sees* (row A). It changes nothing about what the *token may do*. Row 2 is
the same token calling the same tool with no allow-list anywhere, and the
server refused it exactly as it refused the agent in row B. The only thing
that separates row 2 from row 3 is **who the token says is calling**, and
that check lives on the server.

## A. The agent with a client-side allow-list

```
ALLOW-LIST (client side) ['get_account', 'get_card_limits', 'get_member', 'list_cards', 'list_member_accounts', 'list_transactions']
Q: Please freeze my debit card, I lost it   [adhoc/0016]
GATE     use_tool: Member is requesting an action on their own card (freeze a lost debit card); ...
TOOL 1   list_cards({"member_id": "M-1001"}) -> ok   records: CARD-4001
OUTCOME  records_cannot_answer: Member requested a card freeze action, which this assistant cannot perform;
         contact centre assistance is required.
REPLY    I'm not able to freeze your debit card from here, but our contact centre can do that right away
         for you. Please call us immediately so we can protect your account. ...
tools the gate was shown: ['get_account', 'get_card_limits', 'get_member', 'list_cards', 'list_member_accounts', 'list_transactions']
```

The server still advertised all 7 tools (`DISCOVERY … 7 tools`). The agent
filtered its own view. A convenience: fewer tempting tools, cheaper
prompts. Not a control.

## B. The bypass: `scripts/bypass_allowlist.py`

A 100-line MCP client that **does not import the agent**, holding the same
member token. Output, verbatim:

```
=== 1. permitted
    call    get_account({"account_id": "ACC-2001"})
    result  OK  data={"account_id": "ACC-2001", "member_id": "M-1001", "type": "checking", "balance": "4210.55", "status": "active", "opened_on": "2019-03-11"}
    audit   {"caller": "member_assistant", "tool": "get_account", "arguments": {"account_id": "ACC-2001"}, "decision": "allowed", "outcome": "ok", "error": null}

=== 2. the bypass: member token, freeze_card, no agent and no allow-list involved
    call    freeze_card({"card_id": "CARD-4001", "reason": "bypass test"})
    result  REFUSED BY SERVER  code=-32003  forbidden: member_assistant may not call freeze_card
    audit   {"caller": "member_assistant", "tool": "freeze_card", "arguments": {"card_id": "CARD-4001", "reason": "bypass test"}, "decision": "denied", "outcome": "forbidden", "error": "member_assistant may not call freeze_card"}

=== 3. right caller: contact-centre token, same call
    call    freeze_card({"card_id": "CARD-4001", "reason": "member reports card lost"})
    result  OK  data={"card_id": "CARD-4001", "member_id": "M-1001", "account_id": "ACC-2001", "type": "debit", "last_four": "4471", "status": "frozen"}
    audit   {"caller": "contact_centre", "tool": "freeze_card", "arguments": {"card_id": "CARD-4001", "reason": "member reports card lost"}, "decision": "allowed", "outcome": "ok", "error": null}

=== 4. credentials smuggled as an argument
    call    get_account({"account_id": "ACC-2001", "db_password": "hunter2"})
    result  REFUSED BY SERVER  code=-32602  invalid arguments for get_account: undeclared argument(s): db_password
    audit   {"caller": "member_assistant", "tool": "get_account", "arguments": {"account_id": "ACC-2001", "db_password": "[redacted: undeclared argument]"}, "decision": "denied", "outcome": "invalid_arguments", "error": "undeclared argument(s): db_password"}

=== 5. bad token
    call    get_account({"account_id": "ACC-2001"})
    result  CONNECTION REFUSED  MCPError: Server returned an error response
    audit   {"caller": null, "tool": null, "arguments": null, "decision": "denied", "outcome": "unauthenticated", "error": "missing or unknown bearer token"}
    audit   {"caller": null, "tool": null, "arguments": null, "decision": "denied", "outcome": "unauthenticated", "error": "missing or unknown bearer token"}
```

Notes on what the log shows:
- **Case 2 never reached the CRM.** The permission check runs before the
  tool; `tests/test_authorization.py` proves this with a backend that
  counts its calls (zero).
- **Case 4's secret isn't stored.** The server refused the call *and* wrote
  `[redacted: undeclared argument]` instead of the value. Without the
  redaction, the audit log would have become the place the password ended
  up (found in milestone 3, findings log).
- **Case 5 wrote two lines** because the SDK client makes two attempts in
  `mode="auto"` (the newer handshake, then the older one); both `POST /mcp`,
  both 401, 1 ms apart. Each HTTP request is audited. The rejected token
  appears **0 times** in the log.

## Why the credentials can't come from the client (R4)

| Layer | What stops it |
|---|---|
| Tool schemas | No tool declares a credential-like parameter. |
| Server middleware | Every call is validated against the tool's own schema with **undeclared arguments refused** (case 4), before the tool runs. |
| Server config | `CRM_API_KEY` and `HARBOR_DB_PASSWORD` are read only from `mcp_server/.env` (gitignored), by `mcp_server/config.py`. |
| Agent | `tests/test_no_bypass.py`: no HTTP / database / server-package imports in `agent/`, no backend secret names, ports or paths, no hardcoded tool names. Mutation-checked with a planted week-1-style file (milestone 5). |
| Agent process | Live check with a clean environment (`env -i`): only `HARBOR_MCP_TOKEN`; connected and worked (milestone 5). |

## The automated tests (run 2026-09-29)

```
tests/test_authorization.py::test_deny_by_default PASSED
tests/test_authorization.py::test_member_assistant_has_no_write_tools PASSED
tests/test_authorization.py::test_permitted_call_succeeds PASSED
tests/test_authorization.py::test_forbidden_call_is_refused_and_never_reaches_the_backend PASSED
tests/test_authorization.py::test_write_tool_refused_for_member_assistant PASSED
tests/test_authorization.py::test_undeclared_argument_is_refused_and_its_value_never_logged PASSED
tests/test_authorization.py::test_arguments_checked_against_the_tools_schema[args0-pattern] PASSED
tests/test_authorization.py::test_arguments_checked_against_the_tools_schema[args1-missing required argument] PASSED
tests/test_authorization.py::test_arguments_checked_against_the_tools_schema[args2-type] PASSED
tests/test_authorization.py::test_anticipated_backend_failure_is_a_readable_error_result PASSED
tests/test_authorization.py::test_bad_token_cannot_connect[wrong-token] PASSED
tests/test_authorization.py::test_bad_token_cannot_connect[None] PASSED
tests/test_audit.py::test_every_tool_call_writes_exactly_one_line PASSED
tests/test_no_bypass.py::test_only_llm_py_imports_anthropic PASSED
tests/test_no_bypass.py::test_nothing_imports_day6_captioning PASSED
tests/test_no_bypass.py::test_day6_is_reached_only_through_day6_py PASSED
tests/test_no_bypass.py::test_no_module_name_collides_with_day6 PASSED
tests/test_no_bypass.py::test_only_mcp_gateway_imports_mcp PASSED
tests/test_no_bypass.py::test_no_backend_integration_code_in_the_agent PASSED
tests/test_no_bypass.py::test_no_backend_secrets_or_addresses_in_agent_code PASSED
tests/test_no_bypass.py::test_tool_names_are_known_to_this_test PASSED
tests/test_no_bypass.py::test_no_tool_name_is_hardcoded_in_the_agent_or_its_prompts PASSED
tests/test_tool_path.py::test_allow_list_hides_tools_from_the_model PASSED
tests/test_tool_path.py::test_a_hidden_tool_requested_anyway_is_never_sent_to_the_server PASSED
tests/test_tool_path.py::test_real_gateway_and_server_end_to_end PASSED
============================== 25 passed in 4.58s ==============================
```

**The tests can fail.** With the `is_allowed` line in
`mcp_server/middleware.py` disabled, 3 of the authorization/audit tests fail
(milestone 3). That line, run by the SDK around every request before tool
lookup, is the enforcement point.

## What this does not prove (known gaps)

- **Per tool, not per record.** Row 1 would also succeed for someone
  else's account ID: `member_assistant` may call `get_account` for any
  account. The agent passes its session's member ID, but the server doesn't
  check ownership. Production: the member's identity in the token, and a
  per-record check on the server.
- **Static tokens**, no expiry or rotation, over plain HTTP on localhost.
- Full list: `mcp_server/TOOL_MANIFEST.md`, "Known gaps".
