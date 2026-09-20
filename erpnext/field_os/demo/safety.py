"""Prevent demo practice from reaching external communication providers."""

import frappe
from frappe import _


def block_delivery(company):
	if company and frappe.db.exists("Field OS Demo Tenant", {"company": company}):
		frappe.throw(
			_(
				"Demo companies cannot send external email or SMS. Use the synthetic Inbox and approval records for practice."
			)
		)


def validate_email_queue(doc, method=None):
	if doc.reference_doctype and doc.reference_name:
		meta = frappe.get_meta(doc.reference_doctype)
		if meta.has_field("company"):
			block_delivery(frappe.db.get_value(doc.reference_doctype, doc.reference_name, "company"))
