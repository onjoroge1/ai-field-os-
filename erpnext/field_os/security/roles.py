"""Field OS roles and capabilities."""

from __future__ import annotations

from enum import StrEnum


class FieldOSRole(StrEnum):
	OWNER = "Field OS Owner"
	MANAGER = "Field OS Manager"
	DISPATCHER = "Field OS Dispatcher"
	TECHNICIAN = "Field OS Technician"
	BILLING = "Field OS Billing"


ROLE_CAPABILITIES: dict[FieldOSRole, frozenset[str]] = {
	FieldOSRole.OWNER: frozenset({"read", "dispatch", "communicate", "quote", "invoice", "admin"}),
	FieldOSRole.MANAGER: frozenset({"read", "dispatch", "communicate", "quote", "invoice"}),
	FieldOSRole.DISPATCHER: frozenset({"read", "dispatch", "communicate", "quote"}),
	FieldOSRole.TECHNICIAN: frozenset({"read", "field_update", "communicate"}),
	FieldOSRole.BILLING: frozenset({"read", "communicate", "invoice"}),
}
