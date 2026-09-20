"""Persistent contract terms and recurring obligations linked to native service visits."""

import hashlib

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from erpnext.field_os.agreements.service import add_months
from erpnext.field_os.customers.frappe_access import ERPNextCustomerAccessPolicy

AGREEMENT = "Field OS Maintenance Agreement"
VISIT = "Field OS Agreement Visit"
TERMS = ("starts_on", "ends_on", "interval_months", "service_item")


def document(company, name, *, lock=False, doctype=AGREEMENT):
	if not frappe.db.exists(doctype, {"name": name, "company": company}):
		frappe.throw(_("Agreement record is not available in this company"), frappe.PermissionError)
	if lock:
		frappe.db.get_value(doctype, name, "name", for_update=True)
	return frappe.get_doc(doctype, name)


def validate_agreement(doc):
	previous = doc.get_doc_before_save()
	if previous:
		if any(doc.get(key) != previous.get(key) for key in ("company", "customer", "site", "renewed_from")):
			frappe.throw(_("Agreement ownership and renewal links cannot change"))
		if previous.status != "Draft" and any(str(doc.get(key)) != str(previous.get(key)) for key in TERMS):
			frappe.throw(_("Active contract terms are permanent. Create a renewal for new terms."))
		transitions = {
			"Draft": {"Draft", "Active", "Cancelled"},
			"Active": {"Active", "Paused", "Expired", "Cancelled"},
			"Paused": {"Paused", "Active", "Expired", "Cancelled"},
			"Expired": {"Expired"},
			"Cancelled": {"Cancelled"},
		}
		if doc.status not in transitions.get(previous.status, set()):
			frappe.throw(_("Invalid agreement status change"))
	elif doc.status != "Draft":
		frappe.throw(_("New agreements must start as drafts"))
	if not ERPNextCustomerAccessPolicy().can_access(doc.company, doc.customer):
		frappe.throw(_("Customer is not available in this company"), frappe.PermissionError)
	if not frappe.db.exists(
		"Dynamic Link",
		{
			"parenttype": "Address",
			"parent": doc.site,
			"link_doctype": "Customer",
			"link_name": doc.customer,
		},
	):
		frappe.throw(_("Site must belong to the agreement customer"))
	start, end = getdate(doc.starts_on), getdate(doc.ends_on)
	if end <= start or end > add_months(start, 120):
		frappe.throw(_("Agreement term must be positive and no longer than ten years"))
	if not 1 <= doc.interval_months <= 60 or not 0 <= doc.renewal_notice_days <= 365:
		frappe.throw(_("Choose a visit interval of 1–60 months and renewal notice of 0–365 days"))
	if add_months(start, doc.interval_months) > end:
		frappe.throw(_("The agreement must include at least one recurring visit"))
	if not frappe.db.exists(
		"Item", {"name": doc.service_item, "disabled": 0, "is_sales_item": 1, "is_stock_item": 0}
	):
		frappe.throw(_("Select an enabled service item"))
	from erpnext.stock.doctype.company_restriction.company_restriction import validate_masters_for_company

	validate_masters_for_company("Item", [doc.service_item], doc.company)
	if doc.renewed_from:
		old = document(doc.company, doc.renewed_from)
		if (old.customer, old.site) != (doc.customer, doc.site) or start <= getdate(old.ends_on):
			frappe.throw(_("Renewals must follow the original term for the same customer and site"))


def generate_visits(doc):
	"""One obligation per cadence date; completion never shifts the cadence."""
	start, end = getdate(doc.starts_on), getdate(doc.ends_on)
	for months in range(doc.interval_months, 121, doc.interval_months):
		due = add_months(start, months)
		if due > end:
			break
		name = hashlib.sha256(f"{doc.name}:{due}".encode()).hexdigest()
		if not frappe.db.exists(VISIT, name):
			frappe.get_doc(
				{"doctype": VISIT, "company": doc.company, "agreement": doc.name, "due_on": due}
			).insert(ignore_permissions=True, set_name=name)


def detail(company, name):
	doc = document(company, name)
	result = {
		key: doc.get(key)
		for key in (
			"name",
			"company",
			"customer",
			"site",
			"status",
			"starts_on",
			"ends_on",
			"interval_months",
			"renewal_notice_days",
			"service_item",
			"renewed_from",
		)
	}
	result["modified"] = str(doc.modified)
	result["effective_status"] = (
		"Expired" if doc.status in {"Active", "Paused"} and getdate(doc.ends_on) < getdate() else doc.status
	)
	result["renewal"] = frappe.db.get_value(AGREEMENT, {"company": company, "renewed_from": name}, "name")
	result["visits"] = visits(company, name)
	return result


def visits(company, name):
	rows = frappe.get_all(
		VISIT,
		filters={"company": company, "agreement": name},
		fields=["name", "due_on", "maintenance_visit"],
		order_by="due_on asc",
		limit_page_length=0,
	)
	for row in rows:
		row.state = (
			"Overdue"
			if getdate(row.due_on) < getdate()
			else "Due"
			if getdate(row.due_on) <= add_months(getdate(), 1)
			else "Upcoming"
		)
		if row.maintenance_visit:
			job = frappe.db.get_value(
				"Maintenance Visit",
				{"name": row.maintenance_visit, "company": company},
				["docstatus", "completion_status", "mntc_date"],
				as_dict=True,
			)
			if not job:
				frappe.throw(_("Agreement visit has an invalid service job link"))
			row.scheduled_for = job.mntc_date
			row.state = (
				"Cancelled"
				if job.docstatus == 2
				else "Completed"
				if job.docstatus == 1 and job.completion_status == "Fully Completed"
				else "Overdue"
				if getdate(job.mntc_date) < getdate()
				else "Scheduled"
			)
	return rows


def expire_agreements():
	for row in frappe.get_all(
		AGREEMENT,
		filters={"status": ["in", ["Active", "Paused"]], "ends_on": ["<", nowdate()]},
		fields=["name", "company"],
		limit_page_length=0,
	):
		doc = document(row.company, row.name, lock=True)
		if doc.status in {"Active", "Paused"} and getdate(doc.ends_on) < getdate():
			doc.status = "Expired"
			doc.save(ignore_permissions=True)
