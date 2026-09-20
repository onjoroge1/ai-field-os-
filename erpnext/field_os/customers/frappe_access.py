"""Prove that a global ERPNext customer participates in a company tenant."""

from __future__ import annotations

import frappe

COMPANY_CUSTOMER_LINKS = (
	("Field OS HVAC Equipment", "customer"),
	("Sales Invoice", "customer"),
	("Quotation", "party_name"),
	("Maintenance Visit", "customer"),
	("Issue", "customer"),
)


class ERPNextCustomerAccessPolicy:
	def can_access(self, company: str, customer_id: str) -> bool:
		for doctype, customer_field in COMPANY_CUSTOMER_LINKS:
			filters = {"company": company, customer_field: customer_id}
			if doctype == "Quotation":
				filters["quotation_to"] = "Customer"
			if frappe.db.exists(doctype, filters):
				return True
		return False
