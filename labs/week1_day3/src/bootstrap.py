"""Puts day 2's src/ on sys.path so this lab can import its tools, registry,
mock data, errors, and planner modules unchanged. Every other module in this
lab does `import bootstrap  # noqa: F401` before any flat import that needs
to resolve against day 2 (tools, registry, mock_data, errors, planner,
state). See training_instructions/week1_day3.md requirement: "Day 2's own
tool implementations, reused unchanged, so the only thing the diff shows is
the orchestration."
"""

import os
import sys

_DAY2_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "week1_day2", "src")
if _DAY2_SRC not in sys.path:
    sys.path.insert(0, _DAY2_SRC)
