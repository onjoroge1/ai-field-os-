"""Health and readiness endpoints."""

from __future__ import annotations

import frappe

from erpnext.field_os.config import FieldOSConfig, FieldOSConfigError


@frappe.whitelist()
def health() -> dict[str, str]:
	"""Authenticated process-level liveness check."""
	return {"status": "ok", "service": "ai-field-os"}


@frappe.whitelist()
def readiness() -> dict[str, object]:
	"""Authenticated readiness check for application dependencies."""
	config = FieldOSConfig.from_env()
	try:
		config.validate()
	except FieldOSConfigError as exc:
		frappe.throw(str(exc), frappe.ValidationError)

	db_ok = bool(frappe.db.sql("select 1", as_list=True))
	return {
		"status": "ready" if db_ok and config.enabled else "not_ready",
		"database": db_ok,
		"field_os_enabled": config.enabled,
		"environment": config.environment,
		"model_provider_configured": config.model_provider != "disabled",
	}
