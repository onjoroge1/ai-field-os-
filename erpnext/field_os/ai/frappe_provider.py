"""Resolve a deployment-supplied model provider without coupling to a vendor."""

from __future__ import annotations

import frappe

from erpnext.field_os.ai.provider import DisabledModelProvider
from erpnext.field_os.config import FieldOSConfig


def configured_provider(company):
	provider_path = FieldOSConfig.from_env().model_provider
	if provider_path == "disabled":
		return DisabledModelProvider()
	if "." not in provider_path:
		raise ValueError("FIELD_OS_MODEL_PROVIDER must be 'disabled' or an import path")
	provider_factory = frappe.get_attr(provider_path)
	from erpnext.field_os.commercial.metering import MeteredModel

	return MeteredModel(company, provider_factory())
