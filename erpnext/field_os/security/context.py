"""Resolve a request into an explicit tenant/company context."""

from __future__ import annotations

from dataclasses import dataclass

import frappe

from erpnext.field_os.security.roles import FieldOSRole


class TenantAccessDenied(frappe.PermissionError):
	pass


@dataclass(frozen=True, slots=True)
class TenantContext:
	company: str
	user: str
	roles: frozenset[FieldOSRole]
	system_manager: bool = False


def _field_os_roles(user_roles: set[str]) -> frozenset[FieldOSRole]:
	return frozenset(role for role in FieldOSRole if role.value in user_roles)


def _allowed_companies(user: str) -> set[str]:
	return set(
		frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": "Company", "applicable_for": ["in", ["", None, "Company"]]},
			pluck="for_value",
			ignore_permissions=True,
		)
	)


def resolve_tenant_context(company: str, user: str | None = None) -> TenantContext:
	"""Resolve and authorize an explicit company tenant.

	Field OS never silently selects a tenant for a non-System-Manager user.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		raise TenantAccessDenied("Authentication is required")

	if not company or not frappe.db.exists("Company", company):
		raise TenantAccessDenied("A valid company tenant is required")

	user_roles = set(frappe.get_roles(user))
	system_manager = "System Manager" in user_roles

	if not system_manager and company not in _allowed_companies(user):
		raise TenantAccessDenied("User is not permitted for this company")

	roles = _field_os_roles(user_roles)
	if not system_manager and not roles:
		raise TenantAccessDenied("User has no AI Field OS role")

	if getattr(frappe, "local", None) is not None:
		frappe.local.field_os_company = company
	return TenantContext(company=company, user=user, roles=roles, system_manager=system_manager)
