"""Puts src/ and mock_crm/ on sys.path so tests can import their flat
modules directly, without needing a package layout. Import this first in
every test file.

mock_crm/ is included (unlike day 2/3's context.py, which only needed
src/) because tests import the mock CRM's own fixtures module directly
(e.g. to reset fault counters between tests) and conftest.py imports its
FastAPI app to serve it on a background thread -- see conftest.py."""

import os
import sys

_LAB_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_LAB_ROOT, "src"))
sys.path.insert(0, os.path.join(_LAB_ROOT, "mock_crm"))
