"""Owner checkout and recovery plus signature-authenticated provider ingress."""

import frappe

from erpnext.field_os.commercial import billing


@frappe.whitelist()
def status(company: str) -> dict[str, object]:
	return billing.view(company)


@frappe.whitelist(methods=["POST"])
def checkout(company: str, plan: str) -> dict[str, str]:
	return billing.checkout(company, plan)


@frappe.whitelist(methods=["POST"])
def portal(company: str) -> dict[str, str]:
	return billing.portal(company)


@frappe.whitelist(methods=["POST"])
def refresh(company: str) -> dict[str, object]:
	billing.owner(company)
	billing.sync(company)
	return billing.view(company)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook() -> dict[str, bool]:
	return billing.receive(frappe.request.get_data(), frappe.request.headers.get("Stripe-Signature", ""))
