"""Prove that a global ERPNext customer participates in a company tenant."""

from __future__ import annotations

import frappe

COMPANY_CUSTOMER_LINKS = (
	("Field OS Migration Record", "customer"),
	("Field OS HVAC Equipment", "customer"),
	("Sales Invoice", "customer"),
	("Quotation", "party_name"),
	("Maintenance Visit", "customer"),
	("Issue", "customer"),
)


class ERPNextCustomerAccessPolicy:
	def can_access(self, company: str, customer_id: str) -> bool:
		if frappe.db.exists(
			"Customer", {"name": customer_id, "restrict_to_companies": 1}
		) and not frappe.db.exists(
			"Company Restriction",
			{
				"parenttype": "Customer",
				"parent": customer_id,
				"parentfield": "allowed_companies",
				"company": company,
			},
		):
			return False
		for doctype, customer_field in COMPANY_CUSTOMER_LINKS:
			filters = {"company": company, customer_field: customer_id}
			if doctype == "Quotation":
				filters["quotation_to"] = "Customer"
			if frappe.db.exists(doctype, filters):
				return True
		return False
