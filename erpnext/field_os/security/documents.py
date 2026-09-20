"""Apply the same tenant boundary to Desk, REST documents and private files."""

import frappe

from erpnext.field_os.security.authorization import capabilities_for
from erpnext.field_os.security.context import TenantAccessDenied, _allowed_companies, resolve_tenant_context


def equipment_permission(doc, ptype=None, user=None, **kwargs):
	return _permission(doc, ptype, user, "dispatch")


def note_permission(doc, ptype=None, user=None, **kwargs):
	return _permission(doc, ptype, user, "field_update")


def estimate_permission(doc, ptype=None, user=None, **kwargs):
	return _permission(doc, ptype, user, "quote")


def _permission(doc, ptype, user, write_capability):
	try:
		context = resolve_tenant_context(doc.company, user)
	except TenantAccessDenied:
		return False
	capability = (
		"read"
		if ptype in (None, "read", "select", "print", "email", "report", "export")
		else write_capability
	)
	return capability in capabilities_for(context)


def company_query(user=None, doctype=None):
	user = user or frappe.session.user
	if user == "Guest":
		return "1=0"
	if "System Manager" in frappe.get_roles(user):
		return ""
	companies = _allowed_companies(user)
	if not companies:
		return "1=0"
	# The framework supplies doctype, never the request. Keep the identifier allowlisted.
	if doctype not in {
		"Field OS HVAC Equipment",
		"Field OS Equipment Note",
		"Field OS Estimate",
		"Field OS Estimate Decision",
	}:
		return "1=0"
	return frappe.qb.DocType(doctype).company.isin(sorted(companies))
