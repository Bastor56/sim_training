"""Puts src/ on sys.path so tests can import its flat modules directly,
without needing a package layout. pytest loads this file automatically."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
