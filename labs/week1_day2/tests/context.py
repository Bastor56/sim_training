"""Puts src/ on sys.path so tests can import its flat modules directly,
without needing a package layout. Import this first in every test file."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
