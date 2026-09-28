"""Instrumentation rule 1 (spec.md): llm.py is the only door to the Claude API.

Checked on the AST (actual import statements), not with a text grep, so a
docstring that mentions "anthropic" doesn't trip it and an aliased import
can't sneak past it.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
DAY6_SRC = Path(__file__).resolve().parent.parent.parent / "week2_day1" / "src"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_only_llm_py_imports_anthropic():
    offenders = [p.name for p in SRC.glob("*.py") if p.name != "llm.py" and "anthropic" in _imports(p)]
    assert offenders == [], f"these files bypass the wrapper: {offenders}"


def test_nothing_imports_day6_captioning():
    # Day 6's captioning.py builds its own Anthropic client, outside the wrapper.
    offenders = [p.name for p in SRC.glob("*.py") if "captioning" in _imports(p)]
    assert offenders == []


def test_day6_is_reached_only_through_day6_py():
    day6_modules = {p.stem for p in DAY6_SRC.glob("*.py")}
    offenders = {p.name: sorted(_imports(p) & day6_modules)
                 for p in SRC.glob("*.py") if p.name != "day6.py" and _imports(p) & day6_modules}
    assert offenders == {}


def test_no_module_name_collides_with_day6():
    clash = {p.stem for p in SRC.glob("*.py")} & {p.stem for p in DAY6_SRC.glob("*.py")}
    assert clash == set(), f"rename these Day 2 modules: {clash}"
