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


def onboarding_permission(doc, ptype=None, user=None, **kwargs):
	try:
		context = resolve_tenant_context(doc.company, user)
		return ptype in (None, "read", "select") and "admin" in capabilities_for(context)
	except TenantAccessDenied:
		return False


def completion_permission(doc, ptype=None, user=None, **kwargs):
	from erpnext.field_os.completions import repository as repo

	try:
		context = resolve_tenant_context(doc.company, user)
		if doc.doctype == "Field OS Invoice Notice":
			doc = frappe.get_doc(repo.COMPLETION, doc.completion)
		repo.visit(context, doc.visit)
		return ptype in (None, "read", "select", "print", "email", "report", "export")
	except (TenantAccessDenied, frappe.PermissionError, frappe.DoesNotExistError):
		return False


def completion_query(user=None, doctype=None):
	user = user or frappe.session.user
	base = company_query(user, doctype)
	if (isinstance(base, str) and base == "1=0") or set(frappe.get_roles(user)).intersection(
		{"System Manager", "Field OS Owner", "Field OS Manager", "Field OS Dispatcher", "Field OS Billing"}
	):
		return base
	purpose = frappe.qb.DocType("Maintenance Visit Purpose")
	person = frappe.qb.DocType("Sales Person")
	employee = frappe.qb.DocType("Employee")
	assignments = (
		frappe.qb.from_(purpose)
		.join(person)
		.on(person.name == purpose.service_person)
		.join(employee)
		.on(employee.name == person.employee)
		.select(purpose.parent)
		.where((employee.user_id == user) & (employee.status == "Active") & (person.enabled == 1))
	)
	work = frappe.qb.DocType("Field OS Work Completion")
	if doctype == "Field OS Invoice Notice":
		criterion = frappe.qb.DocType(doctype).completion.isin(
			frappe.qb.from_(work).select(work.name).where(work.visit.isin(assignments))
		)
	else:
		criterion = work.visit.isin(assignments)
	return criterion if not base else base & criterion


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
		"Field OS Maintenance Agreement",
		"Field OS Agreement Visit",
		"Field OS Work Completion",
		"Field OS Invoice Notice",
		"Field OS Onboarding",
		"Field OS Migration Batch",
		"Field OS Migration Record",
	}:
		return "1=0"
	return frappe.qb.DocType(doctype).company.isin(sorted(companies))
