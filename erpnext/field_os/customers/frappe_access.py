"""Prove that a global ERPNext customer participates in a company tenant."""

from __future__ import annotations

import frappe


class ERPNextCustomerAccessPolicy:
	def can_access(self, company: str, customer_id: str) -> bool:
		for doctype, customer_field in (
			("Sales Invoice", "customer"),
			("Quotation", "party_name"),
			("Maintenance Visit", "customer"),
			("Issue", "customer"),
		):
			if frappe.db.exists(doctype, {"company": company, customer_field: customer_id}):
				return True
		return False
