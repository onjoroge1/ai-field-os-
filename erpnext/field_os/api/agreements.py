"""Company-scoped agreement management, renewal and service visit scheduling."""

from dataclasses import asdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, getdate

from erpnext.field_os.agreements import frappe_repository as repo
from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.dispatch.frappe_repository import FrappeDispatchRepository
from erpnext.field_os.equipment.frappe_repository import CompanyCustomerAdapter
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context


def context(company, capability="read"):
	ctx = resolve_tenant_context(company)
	authorize(ctx, capability)
	return ctx


def current(doc, modified):
	if not modified or get_datetime(modified) != get_datetime(doc.modified):
		frappe.throw(_("Agreement changed. Reload before saving."), frappe.TimestampMismatchError)


@frappe.whitelist()
def dashboard(company: str, customer_id: str | None = None):
	context(company)
	filters = {"company": company}
	if customer_id:
		CompanyCustomerAdapter(company).get_customer(customer_id)
		filters["customer"] = customer_id
	rows = [
		repo.detail(company, name)
		for name in frappe.get_all(
			repo.AGREEMENT, filters=filters, pluck="name", order_by="ends_on asc", limit=500
		)
	]
	active = [r for r in rows if r["effective_status"] == "Active"]
	return {
		"agreements": rows,
		"counts": {
			"active": len(active),
			"due": sum(v.state == "Due" for r in active for v in r["visits"]),
			"overdue": sum(
				v.state == "Overdue"
				for r in rows
				if r["status"] not in {"Cancelled", "Paused"}
				for v in r["visits"]
			),
			"renewals": sum(
				r["status"] in {"Active", "Paused", "Expired"}
				and not r["renewal"]
				and (getdate(r["ends_on"]) - getdate()).days <= r["renewal_notice_days"]
				for r in rows
			),
		},
		"limit": 500,
	}


@frappe.whitelist()
def get_agreement(company: str, agreement_id: str):
	context(company)
	return repo.detail(company, agreement_id)


@frappe.whitelist()
def options(company: str, customer_id: str):
	context(company, "dispatch")
	adapter = CompanyCustomerAdapter(company)
	adapter.get_customer(customer_id)
	from erpnext.stock.doctype.company_restriction.company_restriction import get_blocked_masters

	names = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1, "is_stock_item": 0},
		pluck="name",
		order_by="name",
		limit=500,
	)
	blocked = get_blocked_masters("Item", names, company) if names else []
	return {
		"sites": [asdict(site) for site in adapter.list_sites(customer_id)],
		"items": [name for name in names if name not in blocked],
		"technicians": [asdict(t) for t in FrappeDispatchRepository().list_technicians(company)],
	}


@frappe.whitelist(methods=["POST"])
@entitled
def save_agreement(
	company: str,
	customer_id: str,
	site_id: str,
	values: dict | str,
	agreement_id: str | None = None,
	modified: str | None = None,
):
	context(company, "dispatch")
	values = frappe.parse_json(values)
	if not isinstance(values, dict) or set(values) - {
		"starts_on",
		"ends_on",
		"interval_months",
		"renewal_notice_days",
		"service_item",
	}:
		frappe.throw(_("Only agreement terms may be updated"))
	if agreement_id:
		doc = repo.document(company, agreement_id, lock=True)
		current(doc, modified)
		if (doc.customer, doc.site) != (customer_id, site_id) or doc.status != "Draft":
			frappe.throw(_("Only a draft's original customer and site may be edited"))
	else:
		doc = frappe.get_doc(
			{
				"doctype": repo.AGREEMENT,
				"company": company,
				"customer": customer_id,
				"site": site_id,
				"status": "Draft",
			}
		)
	doc.update(values)
	doc.save(ignore_permissions=True)
	return repo.detail(company, doc.name)


@frappe.whitelist(methods=["POST"])
@entitled
def set_status(company: str, agreement_id: str, status: str, modified: str):
	context(company, "dispatch")
	doc = repo.document(company, agreement_id, lock=True)
	current(doc, modified)
	if status not in {"Active", "Paused", "Cancelled"}:
		frappe.throw(_("Choose Activate, Pause or Cancel"))
	if status == "Active" and getdate(doc.ends_on) < getdate():
		frappe.throw(_("Expired agreements require renewal"))
	if status == "Cancelled" and any(
		v.maintenance_visit and v.state not in {"Completed", "Cancelled"}
		for v in repo.visits(company, doc.name)
	):
		frappe.throw(_("Complete or cancel scheduled service jobs before cancelling this agreement"))
	doc.status = status
	doc.save(ignore_permissions=True)
	return repo.detail(company, doc.name)


@frappe.whitelist(methods=["POST"])
@entitled
def renew(company: str, agreement_id: str, ends_on: str, modified: str):
	context(company, "dispatch")
	old = repo.document(company, agreement_id, lock=True)
	existing = frappe.db.get_value(repo.AGREEMENT, {"company": company, "renewed_from": old.name}, "name")
	if existing:
		return repo.detail(company, existing)
	current(old, modified)
	if old.status not in {"Active", "Paused", "Expired"}:
		frappe.throw(_("Only an activated agreement can be renewed"))
	doc = frappe.get_doc(
		{
			"doctype": repo.AGREEMENT,
			"company": company,
			"customer": old.customer,
			"site": old.site,
			"status": "Draft",
			"starts_on": add_days(old.ends_on, 1),
			"ends_on": ends_on,
			"interval_months": old.interval_months,
			"renewal_notice_days": old.renewal_notice_days,
			"service_item": old.service_item,
			"renewed_from": old.name,
		}
	).insert(ignore_permissions=True)
	return repo.detail(company, doc.name)


@frappe.whitelist(methods=["POST"])
@entitled
def schedule_visit(company: str, visit_id: str, technician_id: str, scheduled_for: str):
	context(company, "dispatch")
	row = repo.document(company, visit_id, doctype=repo.VISIT)
	# Contract then obligation: consistent lock order across pause, expiry and dispatch.
	agreement = repo.document(company, row.agreement, lock=True)
	row = repo.document(company, visit_id, lock=True, doctype=repo.VISIT)
	if row.maintenance_visit:
		job_status = frappe.db.get_value(
			"Maintenance Visit", {"name": row.maintenance_visit, "company": company}, "docstatus"
		)
		if job_status != 2:
			return {"job": row.maintenance_visit}
	if agreement.status not in {"Active", "Expired"}:
		frappe.throw(_("Activate the agreement before scheduling visits"))
	if technician_id not in {t.id for t in FrappeDispatchRepository().list_technicians(company)}:
		frappe.throw(_("Choose an active technician in this company"))
	when = get_datetime(scheduled_for)
	if when.date() < getdate() or when.date() < getdate(agreement.starts_on):
		frappe.throw(_("Schedule the visit today or later, after the contract starts"))
	FrappeDispatchRepository().ensure_available(
		company, technician_id, when, when + timedelta(hours=2), items=[agreement.service_item]
	)
	job = frappe.get_doc(
		{
			"doctype": "Maintenance Visit",
			"company": company,
			"customer": agreement.customer,
			"customer_address": agreement.site,
			"mntc_date": when.date(),
			"mntc_time": when.time(),
			"maintenance_type": "Scheduled",
			"completion_status": "Partially Completed",
			"purposes": [
				{
					"item_code": agreement.service_item,
					"service_person": technician_id,
					"work_done": "Planned recurring maintenance; completion has not been recorded.",
				}
			],
		}
	).insert(ignore_permissions=True)
	row.maintenance_visit = job.name
	row.save(ignore_permissions=True)
	return {"job": job.name}
