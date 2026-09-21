"""Enforce entitlements independently of HTTP routes or model output."""

from functools import wraps

from erpnext.field_os.commercial.native import require
from erpnext.field_os.security.context import resolve_tenant_context


def entitled(function):
	@wraps(function)
	def checked(company, *args, **kwargs):
		resolve_tenant_context(company)
		module = function.__module__.rsplit(".", 1)[-1]
		feature = {
			"ask": "ai",
			"email": "email",
			"sms": "sms",
			"agreements": "agreements",
			"migrations": "imports",
		}.get(module)
		# Clearing/rejecting never spends credits and remains available after suspension.
		if function.__name__ not in {"clear_conversation", "reject"}:
			require(company, feature)
		return function(company, *args, **kwargs)

	return checked
