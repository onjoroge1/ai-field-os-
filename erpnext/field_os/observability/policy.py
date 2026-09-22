"""Low-cardinality telemetry and explicit provider cost estimates."""

import math

BUCKETS = (50, 100, 250, 500, 1000, 2000, 5000, 15000, 60000)
GROUPS = frozenset(
	{
		"ask",
		"dispatch",
		"equipment",
		"estimates",
		"agreements",
		"completions",
		"email",
		"sms",
		"inbox",
		"onboarding",
		"migrations",
		"commercial",
		"billing",
		"support",
		"jobs",
		"operations",
		"demo",
	}
)


def operation(method):
	parts = str(method or "").split(".")
	return (
		parts[3]
		if len(parts) > 3 and parts[:3] == ["erpnext", "field_os", "api"] and parts[3] in GROUPS
		else "other"
	)


def latency_bucket(milliseconds):
	return next((str(value) for value in BUCKETS if milliseconds <= value), "overflow")


def percentile(values, fraction=0.95):
	total = sum(values.values())
	if not total:
		return None
	seen = 0
	for boundary in (*BUCKETS, "overflow"):
		seen += values.get(str(boundary), 0)
		if seen >= math.ceil(total * fraction):
			return boundary


def cost_microusd(input_tokens, output_tokens, rates):
	if any(
		isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 100_000_000
		for n in (input_tokens, output_tokens)
	):
		return None
	if not isinstance(rates, dict) or set(rates) != {"input", "output"}:
		return None
	if any(
		isinstance(n, bool) or not isinstance(n, int | float) or not math.isfinite(n) or not 0 <= n <= 10000
		for n in rates.values()
	):
		return None
	# USD per million tokens is numerically equal to micro-USD per token.
	return round(input_tokens * rates["input"] + output_tokens * rates["output"])
