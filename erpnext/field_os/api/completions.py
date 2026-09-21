"""Technician evidence, native completion and explicit financial approval endpoints."""

import json

import frappe
from frappe import _

from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.completions import repository as repo
from erpnext.field_os.dispatch.frappe_repository import FrappeDispatchRepository
from erpnext.field_os.security.authorization import capabilities_for


@frappe.whitelist()
def list_work(company: str):
	ctx = repo.context(company)
	filters = {"company": company, "docstatus": ["!=", 2]}
	if not capabilities_for(ctx).intersection({"dispatch", "invoice", "admin"}):
		technicians = [
			t.id for t in FrappeDispatchRepository().list_technicians(company) if t.user == ctx.user
		]
		if not technicians:
			return []
		filters["name"] = [
			"in",
			frappe.get_all(
				"Maintenance Visit Purpose", filters={"service_person": ["in", technicians]}, pluck="parent"
			),
		]
	rows = frappe.get_all(
		"Maintenance Visit",
		filters=filters,
		fields=["name", "customer", "customer_address", "mntc_date", "docstatus"],
		order_by="mntc_date desc",
		limit=200,
	)
	for row in rows:
		completion = frappe.db.get_value(
			repo.COMPLETION, {"company": company, "visit": row.name}, ["name", "status"], as_dict=True
		)
		row.completion = completion.name if completion else None
		row.status = (
			completion.status if completion else "Scheduled" if row.docstatus == 0 else "Completed in ERPNext"
		)
	return rows


@frappe.whitelist()
def get_completion(company: str, completion_id: str):
	return repo.detail(repo.context(company), completion_id)


@frappe.whitelist(methods=["POST"])
@entitled
def start_completion(company: str, visit_id: str):
	ctx = repo.context(company, "field_update")
	job = repo.visit(ctx, visit_id, write=True, lock=True)
	if existing := frappe.db.get_value(repo.COMPLETION, {"company": company, "visit": visit_id}, "name"):
		return repo.detail(ctx, existing)
	if job.docstatus != 0:
		frappe.throw(_("Start a completion from a planned service job"))
	doc = frappe.get_doc(
		{
			"doctype": repo.COMPLETION,
			"company": company,
			"customer": job.customer,
			"site": job.customer_address,
			"visit": visit_id,
			"visit_modified": job.modified,
			"status": "Draft",
			"checklist_json": json.dumps(dict.fromkeys(repo.CHECKS, False)),
			"billables_json": "[]",
			"photos_json": "[]",
		}
	).insert(ignore_permissions=True)
	return repo.detail(ctx, doc.name)


@frappe.whitelist(methods=["POST"])
@entitled
def save_completion(company: str, completion_id: str, values: dict | str, version: str):
	ctx = repo.context(company, "field_update")
	doc, job = repo.document(ctx, completion_id, write=True, lock=True)
	repo.current(doc, job, version)
	if doc.status != "Draft" or job.docstatus != 0:
		frappe.throw(_("Completed service evidence cannot be edited"))
	values = frappe.parse_json(values)
	if not isinstance(values, dict) or set(values) - {
		"summary",
		"checklist",
		"billables",
		"signature",
		"signer_name",
		"photos",
	}:
		frappe.throw(_("Only service evidence and billables may be edited"))
	for key in ("summary", "signer_name", "signature"):
		if key in values:
			value = values[key]
			if not isinstance(value, str) or len(value) > (2000 if key == "summary" else 500):
				frappe.throw(_("Service evidence text is too long"))
			doc.set(key, value.strip())
	for key in ("checklist", "billables", "photos"):
		if key in values:
			doc.set(key + "_json", json.dumps(values[key]))
	doc.visit_modified = job.modified
	doc.save(ignore_permissions=True)
	return repo.detail(ctx, doc.name)


@frappe.whitelist(methods=["POST"])
@entitled
def upload_evidence(company: str, completion_id: str, content: str, kind: str = "Photo"):
	from erpnext.field_os.completions.media import save_image

	ctx = repo.context(company, "field_update")
	doc, job = repo.document(ctx, completion_id, write=True, lock=True)
	if doc.status != "Draft" or job.docstatus != 0:
		frappe.throw(_("Evidence can only be attached to draft service work"))
	return save_image(doc, content, kind)


@frappe.whitelist(methods=["POST"])
@entitled
def complete(company: str, completion_id: str, version: str):
	return repo.finish(repo.context(company, "field_update"), completion_id, version)


@frappe.whitelist()
def options(company: str, completion_id: str):
	from erpnext.field_os.estimates.frappe_repository import recipients
	from erpnext.stock.doctype.company_restriction.company_restriction import get_blocked_masters

	ctx = repo.context(company)
	doc, _ = repo.document(ctx, completion_id)
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=["name", "is_stock_item", "standard_rate"],
		order_by="name",
		limit=500,
	)
	blocked = get_blocked_masters("Item", [i.name for i in items], company) if items else []
	from erpnext.field_os.onboarding.native import config

	return {
		"defaults": config(company, "notifications"),
		"currency": frappe.db.get_value("Company", company, "default_currency"),
		"items": [i for i in items if i.name not in blocked],
		"warehouses": frappe.get_all(
			"Warehouse", filters={"company": company, "disabled": 0, "is_group": 0}, pluck="name"
		),
		"recipients": recipients(doc.customer),
		"integrations": frappe.get_all(
			"Field OS Email Integration",
			filters={"company": company, "enabled": 1},
			fields=["name", "from_address"],
		),
		"tax_templates": frappe.get_all(
			"Sales Taxes and Charges Template", filters={"company": company, "disabled": 0}, pluck="name"
		),
	}


@frappe.whitelist(methods=["POST"])
@entitled
def preview_invoice(company: str, completion_id: str, due_date: str, tax_template: str = ""):
	from erpnext.field_os.completions import billing

	return billing.preview(repo.context(company, "invoice"), completion_id, due_date, tax_template)


@frappe.whitelist(methods=["POST"])
@entitled
def approve_invoice(company: str, proposal_id: str, idempotency_key: str):
	from erpnext.field_os.completions import billing

	return billing.approve(repo.context(company, "invoice"), proposal_id, idempotency_key)


@frappe.whitelist(methods=["POST"])
@entitled
def preview_notice(
	company: str, completion_id: str, recipient: str, integration_id: str, kind: str = "Invoice"
):
	from erpnext.field_os.completions import notices

	return notices.preview(repo.context(company, "invoice"), completion_id, recipient, integration_id, kind)


@frappe.whitelist(methods=["POST"])
@entitled
def approve_notice(company: str, proposal_id: str, idempotency_key: str):
	from erpnext.field_os.completions import notices

	return notices.approve(repo.context(company, "invoice"), proposal_id, idempotency_key)
