"""Company and assignment scoped service evidence backed by native Maintenance Visits."""

import hashlib
import json
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime, nowdate, strip_html

from erpnext.field_os.dispatch.frappe_repository import FrappeDispatchRepository
from erpnext.field_os.estimates.frappe_repository import stock
from erpnext.field_os.security.authorization import authorize, capabilities_for
from erpnext.field_os.security.context import resolve_tenant_context
from erpnext.stock.doctype.company_restriction.company_restriction import validate_masters_for_company

COMPLETION = "Field OS Work Completion"
NOTICE = "Field OS Invoice Notice"
CHECKS = {
	"safety_checks": "Safety checks complete",
	"operational_test": "System operation verified",
	"work_area_clean": "Work area left clean",
}
EVIDENCE = (
	"checklist_json",
	"billables_json",
	"signature",
	"signer_name",
	"photos_json",
	"summary",
	"completed_by",
	"completed_at",
)


def context(company, capability="read"):
	ctx = resolve_tenant_context(company)
	authorize(ctx, capability)
	return ctx


def visit(context, name, *, write=False, lock=False):
	if not frappe.db.exists("Maintenance Visit", {"name": name, "company": context.company}):
		frappe.throw(_("Service job is not available in this company"), frappe.PermissionError)
	if lock:
		frappe.db.get_value("Maintenance Visit", name, "name", for_update=True)
	doc = frappe.get_doc("Maintenance Visit", name)
	caps = capabilities_for(context)
	if write:
		authorize(context, "field_update")
	if write or not caps.intersection({"dispatch", "invoice", "admin"}):
		technicians = {
			t.id
			for t in FrappeDispatchRepository().list_technicians(context.company)
			if t.user == context.user
		}
		if not any(row.service_person in technicians for row in doc.purposes):
			frappe.throw(_("This service job is assigned to another technician"), frappe.PermissionError)
	return doc


def document(context, name, *, write=False, lock=False):
	if not frappe.db.exists(COMPLETION, {"name": name, "company": context.company}):
		frappe.throw(_("Completion is not available in this company"), frappe.PermissionError)
	if lock:
		frappe.db.get_value(COMPLETION, name, "name", for_update=True)
	doc = frappe.get_doc(COMPLETION, name)
	job = visit(context, doc.visit, write=write, lock=lock)
	if (doc.customer, doc.site) != (job.customer, job.customer_address):
		frappe.throw(_("Completion and service job ownership do not match"), frappe.PermissionError)
	return doc, job


def version(doc, job):
	return hashlib.sha256(f"{doc.modified}:{job.modified}:{job.docstatus}".encode()).hexdigest()


def current(doc, job, expected):
	if not expected or version(doc, job) != expected:
		frappe.throw(_("Service work changed. Reload before continuing."), frappe.TimestampMismatchError)


def validate_lines(company, lines):
	if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
		frappe.throw(_("Enter between one and one hundred billable lines"))
	for row in lines:
		if not isinstance(row, dict) or set(row) - {"item_code", "qty", "rate", "warehouse"}:
			frappe.throw(_("Only item, quantity, rate and warehouse are allowed"))
		try:
			qty, rate = Decimal(str(row.get("qty"))), Decimal(str(row.get("rate")))
		except (InvalidOperation, ValueError):
			frappe.throw(_("Billables require valid quantities and rates"))
		if not qty.is_finite() or not rate.is_finite() or not 0 < qty <= 10000 or not 0 <= rate <= 1000000:
			frappe.throw(_("Billable quantities or rates are outside the allowed range"))
		if not frappe.db.exists("Item", {"name": row.get("item_code"), "disabled": 0, "is_sales_item": 1}):
			frappe.throw(_("Choose an enabled sales item"))
		validate_masters_for_company("Item", [row["item_code"]], company)
		stock(company, row["item_code"], row.get("warehouse"))
	return lines


def validate_document(doc):
	job = frappe.db.get_value(
		"Maintenance Visit", doc.visit, ["company", "customer", "customer_address"], as_dict=True
	)
	if not job or (job.company, job.customer, job.customer_address) != (doc.company, doc.customer, doc.site):
		frappe.throw(_("Completion must belong to its service job's company, customer and site"))
	previous = doc.get_doc_before_save()
	if previous:
		if any(previous.get(k) != doc.get(k) for k in ("company", "customer", "site", "visit")):
			frappe.throw(_("Completion ownership cannot change"))
		if previous.status != "Draft" and any(str(previous.get(k)) != str(doc.get(k)) for k in EVIDENCE):
			frappe.throw(_("Completed service evidence is permanent"))
	checks = frappe.parse_json(doc.checklist_json or "{}")
	photos = frappe.parse_json(doc.photos_json or "[]")
	lines = frappe.parse_json(doc.billables_json or "[]")
	if (
		not isinstance(checks, dict)
		or set(checks) - set(CHECKS)
		or any(not isinstance(x, bool) for x in checks.values())
	):
		frappe.throw(_("Use the required service checklist"))
	if not isinstance(photos, list) or len(photos) > 20 or any(not isinstance(p, str) for p in photos):
		frappe.throw(_("Attach up to twenty service photos"))
	for url in [*photos, *([doc.signature] if doc.signature else [])]:
		if not url.startswith("/private/files/") or not frappe.db.exists(
			"File",
			{
				"file_url": url,
				"is_private": 1,
				"attached_to_doctype": COMPLETION,
				"attached_to_name": doc.name,
			},
		):
			frappe.throw(_("Evidence must be private attachments of this completion"), frappe.PermissionError)
	if doc.signature and not frappe.db.exists(
		"File",
		{
			"file_url": doc.signature,
			"attached_to_doctype": COMPLETION,
			"attached_to_name": doc.name,
			"attached_to_field": "signature",
			"is_private": 1,
		},
	):
		frappe.throw(_("Capture the customer signature using the signature field"))
	if lines:
		validate_lines(doc.company, lines)
	if doc.status != "Draft" and (
		set(checks) != set(CHECKS)
		or not all(checks.values())
		or not photos
		or not doc.signature
		or not (doc.signer_name or "").strip()
		or not strip_html(doc.summary or "").strip()
		or not lines
	):
		frappe.throw(
			_("Complete the checklist, work summary, customer signature, photos and billables first")
		)
	for invoice in (doc.proposed_invoice, doc.invoice):
		if invoice and not frappe.db.exists(
			"Sales Invoice", {"name": invoice, "company": doc.company, "customer": doc.customer}
		):
			frappe.throw(_("Invoice must belong to the same company and customer"))


def detail(context, name):
	doc, job = document(context, name)
	result = {
		k: doc.get(k)
		for k in (
			"name",
			"visit",
			"customer",
			"site",
			"status",
			"summary",
			"signature",
			"signer_name",
			"completed_by",
			"completed_at",
			"invoice",
			"proposed_invoice",
			"invoice_approved_by",
		)
	}
	result.update(
		currency=frappe.db.get_value("Company", context.company, "default_currency"),
		version=version(doc, job),
		scheduled_for=job.mntc_date,
		checklist=frappe.parse_json(doc.checklist_json or "{}"),
		photos=frappe.parse_json(doc.photos_json or "[]"),
		billables=frappe.parse_json(doc.billables_json or "[]"),
		required_checks=CHECKS,
	)
	result["notices"] = frappe.get_all(
		NOTICE,
		filters={"company": context.company, "completion": name},
		fields=["kind", "recipient", "creation", "email_queue"],
		order_by="creation desc",
		limit=50,
	)
	for notice in result["notices"]:
		notice.delivery_status = frappe.db.get_value("Email Queue", notice.email_queue, "status")
	if doc.invoice:
		result["financials"] = frappe.db.get_value(
			"Sales Invoice",
			doc.invoice,
			["name", "currency", "grand_total", "outstanding_amount", "due_date", "docstatus", "status"],
			as_dict=True,
		)
	return result


def finish(context, name, expected):
	doc, job = document(context, name, write=True, lock=True)
	current(doc, job, expected)
	if doc.status != "Draft" or job.docstatus != 0:
		frappe.throw(_("Only draft service work can be completed"))
	if getdate(job.mntc_date) > getdate():
		frappe.throw(_("A future service visit cannot be completed"))
	doc.status, doc.completed_by, doc.completed_at = "Completed", context.user, now_datetime()
	validate_document(doc)
	job.completion_status = "Fully Completed"
	job.mntc_date = nowdate()
	job.mntc_time = now_datetime().time()
	for row in job.purposes:
		row.work_done = strip_html(doc.summary)
	job.flags.ignore_permissions = True
	job.submit()
	doc.visit_modified = job.modified
	doc.save(ignore_permissions=True)
	return detail(context, name)
