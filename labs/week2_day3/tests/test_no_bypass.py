"""The agent has exactly two doors, and no hidden third one (spec.md R4, R7, "No direct integration").

  - llm.py is the only door to the Claude API (Day 2's instrumentation rule 1);
  - mcp_gateway.py is the only door to Harbor's records.

Day 3 adds the second rule, and its teeth: no agent file may contain backend
integration code (HTTP / database clients), backend credentials or
addresses, the server's own package, or a hardcoded tool name. Week 1's agent
had all of those in its tool_client.py; this is what "deleted, not dormant"
means here (spec.md decision 7).

Checked on the AST (actual import statements) where it's about imports, so
a docstring mentioning "httpx" doesn't trip it and an aliased import can't
sneak past. Checked on the text where it's about secrets and names.
"""

import ast
import re
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
SRC = LAB / "agent"
PROMPTS = LAB / "prompts"
DAY6_SRC = LAB.parent / "week2_day1" / "src"

AGENT_FILES = sorted(SRC.glob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _code_only(path: Path) -> str:
    """The file's source with docstrings removed, so explanations may name what the code may not use."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ---------------------------------------------------------------- Day 2's rules, carried over

def test_only_llm_py_imports_anthropic():
    offenders = [p.name for p in AGENT_FILES if p.name != "llm.py" and "anthropic" in _imports(p)]
    assert offenders == [], f"these files bypass the wrapper: {offenders}"


def test_nothing_imports_day6_captioning():
    # Day 6's captioning.py builds its own Anthropic client, outside the wrapper.
    offenders = [p.name for p in AGENT_FILES if "captioning" in _imports(p)]
    assert offenders == []


def test_day6_is_reached_only_through_day6_py():
    day6_modules = {p.stem for p in DAY6_SRC.glob("*.py")}
    offenders = {p.name: sorted(_imports(p) & day6_modules)
                 for p in AGENT_FILES if p.name != "day6.py" and _imports(p) & day6_modules}
    assert offenders == {}


def test_no_module_name_collides_with_day6():
    clash = {p.stem for p in AGENT_FILES} & {p.stem for p in DAY6_SRC.glob("*.py")}
    assert clash == set(), f"rename these agent modules: {clash}"


# ---------------------------------------------------------------- Day 3: MCP is the only door to the records

def test_only_mcp_gateway_imports_mcp():
    offenders = [p.name for p in AGENT_FILES
                 if p.name != "mcp_gateway.py" and _imports(p) & {"mcp", "mcp_types", "httpx2"}]
    assert offenders == [], f"these files talk MCP outside the gateway: {offenders}"


BANNED_IMPORTS = {
    "httpx": "an HTTP client (week 1's tool_client.py used this to reach the CRM)",
    "requests": "an HTTP client",
    "urllib": "an HTTP client",
    "aiohttp": "an HTTP client",
    "psycopg": "a Postgres driver",
    "psycopg2": "a Postgres driver",
    "sqlalchemy": "a database toolkit",
    "fastapi": "the mock CRM's framework",
    "mcp_server": "the server's own package: the agent must reach it over MCP, never import it",
}


def test_no_backend_integration_code_in_the_agent():
    offenders = {p.name: {m: why for m, why in BANNED_IMPORTS.items() if m in _imports(p)}
                 for p in AGENT_FILES}
    assert {k: v for k, v in offenders.items() if v} == {}


BANNED_TEXT = [
    r"CRM_API_KEY", r"X-API-Key", r"HARBOR_DB_", r"MCP_TOKEN_",   # backend / server-side secret names
    r":8100\b", r":54322\b", r"harbor_core\.", r"/members/", r"/cards/",  # backend addresses and paths
    r"mcp_server[/.]\.env", r"postgresql://",
]


def test_no_backend_secrets_or_addresses_in_agent_code():
    offenders = {}
    for p in AGENT_FILES:
        code = _code_only(p)
        hits = [pat for pat in BANNED_TEXT if re.search(pat, code)]
        if hits:
            offenders[p.name] = hits
    assert offenders == {}


def _all_tool_names() -> set[str]:
    # Read the server's permission map as TEXT, so this test doesn't import the server into the agent's tests' process
    # just to learn names. Every tool the server has is in there (deny by default: an ungranted tool is unusable).
    text = (LAB / "mcp_server" / "permissions.py").read_text(encoding="utf-8")
    names = set(re.findall(r'"([a-z]+_[a-z_]+)"', text))
    return names - {"member_assistant", "contact_centre"}


def test_tool_names_are_known_to_this_test():
    assert {"get_member", "list_cards", "freeze_card", "get_account"} <= _all_tool_names()


def test_no_tool_name_is_hardcoded_in_the_agent_or_its_prompts():
    """R2: the agent learns the tool list from the server. A tool name written into
    agent code or a prompt is knowledge that would go stale when the server changes."""
    names = _all_tool_names()
    offenders = {}
    for p in AGENT_FILES:
        hits = sorted(n for n in names if re.search(rf"\b{n}\b", _code_only(p)))
        if hits:
            offenders[p.name] = hits
    for p in sorted(PROMPTS.glob("*.md")):
        hits = sorted(n for n in names if re.search(rf"\b{n}\b", p.read_text(encoding="utf-8")))
        if hits:
            offenders[f"prompts/{p.name}"] = hits
    assert offenders == {}
