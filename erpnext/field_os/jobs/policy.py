"""Retry policy deliberately separates known failures from ambiguous side effects."""

MAX_ATTEMPTS = 5


def failure_state(*, attempts, dispatched, replay_safe, permanent=False):
	if dispatched and not replay_safe:
		return "Uncertain"
	if permanent or attempts >= MAX_ATTEMPTS:
		return "Dead"
	return "Retry"


def retry_seconds(attempts):
	return min(3600, 30 * (2 ** max(0, min(attempts - 1, 7))))
