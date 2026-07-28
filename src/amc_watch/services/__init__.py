"""Per-process entry points.

Each service exposes a synchronous `run_once()` that tests drive directly; the scheduling
wrapper around it stays a thin, untested shell (parent #1, "Testing Decisions").
Skeleton only: poller lands in #4/#7, matcher+notifier in #4.
"""
