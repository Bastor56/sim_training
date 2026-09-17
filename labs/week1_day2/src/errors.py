"""Exception types shared across the loop.

Only ToolError is special-cased anywhere (executor.py catches exactly this
and retries with backoff). Everything else — a typo in dispatch code, a bad
tool signature, a malformed planner response — is a harness bug and is left
to propagate as a normal Python exception, per spec.md's tool-error vs.
harness-error distinction.
"""


class ToolError(Exception):
    """Recoverable tool failure: a bad lookup, a simulated timeout, a flaky
    third-party service. Fed back to the planner as an observation once
    retries are exhausted — never lets the run crash."""
