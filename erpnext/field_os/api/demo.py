"""Guided synthetic sandboxes with administrator-controlled provisioning and reset."""

import frappe

from erpnext.field_os.demo import native


@frappe.whitelist()
def get_demo(company: str):
	return native.status(company)


@frappe.whitelist(methods=["POST"])
def use_company(company: str):
	ctx = native.resolve_tenant_context(company)
	native.authorize(ctx, "read")
	frappe.defaults.set_user_default("company", company, ctx.user)
	return {"company": company}


@frappe.whitelist(methods=["POST"])
def create(label: str, password: str, idempotency_key: str):
	return native.create(label, password, idempotency_key)


@frappe.whitelist(methods=["POST"])
def preview_reset(company: str):
	return native.preview_reset(company)


@frappe.whitelist(methods=["POST"])
def approve_reset(company: str, proposal_id: str, idempotency_key: str, password: str):
	return native.reset(company, proposal_id, idempotency_key, password)
