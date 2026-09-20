"""Shared pytest fixtures.

mock_crm_base_url starts the real mock CRM app under uvicorn, on a
background thread, on an OS-assigned free port -- genuine sockets, genuine
timeout behavior. This was chosen over FastAPI/Starlette's TestClient
(which drives the ASGI app in-process) after TestClient turned out not to
support a client-side timeout override at all (its own constructor
refuses a `timeout` argument) -- and a real socket timeout is exactly
what tests/test_tool_client.py's timeout case needs to exercise. It also
means even the test suite is talking to something that behaves like "a
real HTTP service" per the lab's own requirement, not an in-process
shortcut.

conftest.py loads before any test module runs, so it can't assume
tests/context.py has already put src/ and mock_crm/ on sys.path -- it
repeats that file's two-line setup directly instead of importing it.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mock_crm"))

import httpx
import pytest
import uvicorn

import app as mock_app


class _BackgroundUvicornServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        # uvicorn only allows installing signal handlers on the main
        # thread; this server always runs on a background thread.
        pass


@pytest.fixture(scope="session")
def mock_crm_base_url():
    config = uvicorn.Config(mock_app.app, host="127.0.0.1", port=0, log_level="warning")
    server = _BackgroundUvicornServer(config=config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5.0
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("mock CRM server did not start within 5s")
        time.sleep(0.01)

    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    with httpx.Client(base_url=base_url, timeout=2.0) as probe:
        probe.get("/health").raise_for_status()

    yield base_url

    server.should_exit = True
    thread.join(timeout=5.0)
