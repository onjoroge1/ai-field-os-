"""Frappe validation and persistence used by Inbox corrections."""

from __future__ import annotations

import frappe

from erpnext.field_os.customers.frappe_access import ERPNextCustomerAccessPolicy
from erpnext.field_os.inbox.models import CorrectionFeedback
from erpnext.field_os.security.roles import FieldOSRole


class FrappeCorrectionStore:
	def save(self, feedback: CorrectionFeedback) -> CorrectionFeedback:
		frappe.get_doc(
			{
				"doctype": "Field OS Inbox Correction",
				"company": feedback.company,
				"thread": feedback.thread_id,
				"message": feedback.message_id,
				"corrected_field": feedback.field,
				"previous_value": feedback.previous_value,
				"corrected_value": feedback.corrected_value,
				"actor": feedback.actor,
				"occurred_at": feedback.occurred_at,
				"reason": feedback.reason,
			}
		).insert()
		return feedback


class FrappeCorrectionPolicy:
	_CLASSIFICATIONS = frozenset(
		{"safety_emergency", "service_request", "billing", "general", "spam", "consent"}
	)

	def validate(self, company, thread, field, value):
		if field == "classification":
			if value not in self._CLASSIFICATIONS:
				raise ValueError("Unsupported classification")
			return
		if field == "customer_id":
			if not ERPNextCustomerAccessPolicy().can_access(company, value):
				raise PermissionError("Customer is not available in this tenant")
			return
		mapping = {
			"site_id": ("Address", None),
			"equipment_id": ("Serial No", None),
			"service_request_id": ("Issue", "company"),
			"job_id": ("Maintenance Visit", "company"),
			"quote_id": ("Quotation", "company"),
			"invoice_id": ("Sales Invoice", "company"),
		}
		if field not in mapping:
			raise ValueError("Unsupported correction field")
		doctype, company_field = mapping[field]
		filters = {"name": value}
		if company_field:
			filters[company_field] = company
		if not frappe.db.exists(doctype, filters):
			raise PermissionError("Linked record is not available in this tenant")
		if field in {"site_id", "equipment_id"}:
			if not thread.links.customer_id:
				raise ValueError("Link a customer before linking site or equipment")
			if field == "site_id" and not frappe.db.exists(
				"Dynamic Link",
				{
					"parenttype": "Address",
					"parent": value,
					"link_doctype": "Customer",
					"link_name": thread.links.customer_id,
				},
			):
				raise PermissionError("Site is not linked to this customer")
			if field == "equipment_id" and not frappe.db.exists(
				"Serial No", {"name": value, "customer": thread.links.customer_id}
			):
				raise PermissionError("Equipment is not linked to this customer")


class FrappeAssigneePolicy:
	def validate(self, company: str, user: str) -> None:
		if not frappe.db.exists("User", {"name": user, "enabled": 1}):
			raise ValueError("Assignee is not an active user")
		roles = set(frappe.get_roles(user))
		if "System Manager" in roles:
			return
		if not roles.intersection(role.value for role in FieldOSRole):
			raise PermissionError("Assignee has no Field OS role")
		allowed = frappe.db.exists(
			"User Permission", {"user": user, "allow": "Company", "for_value": company}
		)
		if not allowed:
			raise PermissionError("Assignee is not permitted for this company")


class FrappeServiceRequestCreator:
	def create(self, context, thread, summary):
		sender = next((item for item in thread.participants if item.role.value == "customer"), None)
		doc = frappe.get_doc(
			{
				"doctype": "Issue",
				"company": context.company,
				"customer": thread.links.customer_id,
				"subject": thread.subject[:140],
				"description": summary,
				"raised_by": sender.address if sender and "@" in sender.address else context.user,
			}
		)
		doc.insert()
		return doc.name
