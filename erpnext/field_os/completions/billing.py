"""Native draft invoices become ledger entries only after a bound financial approval."""

import hashlib
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, nowdate

from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.actions.validation import require_proposal
from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.completions import repository as repo
from erpnext.field_os.security.authorization import authorize
from erpnext.stock.get_item_details import get_item_details


def retry_key(context, tool, key):
	if not key or len(key) > 140:
		frappe.throw(_("A retry key of at most 140 characters is required"))
	return hashlib.sha256(f"{context.company}\0{context.user}\0{tool}\0{key}".encode()).hexdigest()


def proposal(context, tool, arguments, risk):
	now = datetime.now(UTC)
	item = ActionProposal(
		str(uuid4()), tool, arguments, risk, context.company, context.user, now, now + timedelta(minutes=10)
	)
	FrappeCacheProposalStore().save(item)
	return item


def load_proposal(context, name, tool, risk):
	item = require_proposal(
		FrappeCacheProposalStore().load(context.company, name), context, tool=tool, risk=risk
	)
	if item.expires_at <= datetime.now(UTC):
		frappe.throw(_("Approval expired. Review a new preview."))
	return item


def invoice_document(doc, *, lock=False):
	name = doc.invoice or doc.proposed_invoice
	if not name or not frappe.db.exists(
		"Sales Invoice", {"name": name, "company": doc.company, "customer": doc.customer}
	):
		frappe.throw(_("Invoice is not available for this service work"), frappe.PermissionError)
	if lock:
		frappe.db.get_value("Sales Invoice", name, "name", for_update=True)
	return frappe.get_doc("Sales Invoice", name)


def payable(invoice):
	return invoice.grand_total if invoice.is_rounded_total_disabled() else invoice.rounded_total


def amounts(invoice):
	return {
		"currency": invoice.currency,
		"total": payable(invoice),
		"before_rounding": invoice.grand_total,
		"rounding": invoice.rounding_adjustment,
		"taxes": invoice.total_taxes_and_charges,
		"items": [
			{
				"item_code": r.item_code,
				"qty": r.qty,
				"rate": r.rate,
				"amount": r.amount,
				"warehouse": r.warehouse,
			}
			for r in invoice.items
		],
	}


def preview(context, name, due, tax_template):
	authorize(context, "invoice")
	doc, job = repo.document(context, name, lock=True)
	if (
		doc.status != "Completed"
		or job.docstatus != 1
		or get_datetime(doc.visit_modified) != get_datetime(job.modified)
	):
		frappe.throw(_("Only unchanged, completed service work is invoice-ready"))
	if getdate(due) < getdate():
		frappe.throw(_("Invoice due date must be today or later"))
	repo.validate_document(doc)
	company = frappe.get_doc("Company", context.company)
	price_list = frappe.db.get_value(
		"Customer", doc.customer, "default_price_list"
	) or frappe.db.get_single_value("Selling Settings", "selling_price_list")
	if not price_list or not frappe.db.exists(
		"Price List", {"name": price_list, "enabled": 1, "selling": 1, "currency": company.default_currency}
	):
		frappe.throw(_("Configure a selling price list in the company currency"))
	if doc.proposed_invoice:
		invoice = invoice_document(doc, lock=True)
		if invoice.docstatus:
			frappe.throw(_("Proposed invoice is no longer a draft"))
	else:
		invoice = frappe.new_doc("Sales Invoice")
	invoice.update(
		{
			"company": context.company,
			"customer": doc.customer,
			"customer_address": doc.site,
			"posting_date": nowdate(),
			"due_date": due,
			"currency": company.default_currency,
			"selling_price_list": price_list,
			"price_list_currency": company.default_currency,
			"conversion_rate": 1,
			"plc_conversion_rate": 1,
			"update_stock": 0,
			"remarks": f"Service completion {doc.name}; visit {doc.visit}. {doc.summary}",
		}
	)
	invoice.set("items", [])
	for row in frappe.parse_json(doc.billables_json):
		stocked = frappe.db.get_value("Item", row["item_code"], "is_stock_item")
		invoice.update_stock = invoice.update_stock or stocked
		details = get_item_details(
			{
				**invoice.as_dict(),
				**row,
				"doctype": "Sales Invoice",
				"price_list": price_list,
			},
			invoice,
		)
		# Resolve the same company/item accounting defaults as the native item picker.
		invoice.append(
			"items",
			{
				**details,
				**row,
				"income_account": details.get("income_account") or company.default_income_account,
				"expense_account": details.get("expense_account") or company.default_expense_account,
				"cost_center": details.get("cost_center") or company.cost_center,
			},
		)
	invoice.set("taxes", [])
	invoice.taxes_and_charges = tax_template or None
	if tax_template:
		if not frappe.db.exists(
			"Sales Taxes and Charges Template",
			{"name": tax_template, "company": context.company, "disabled": 0},
		):
			frappe.throw(_("Select a tax template in this company"))
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		invoice.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", tax_template))
	# This is an unsubmitted accounting draft. No debt or stock movement is posted here.
	invoice.save(ignore_permissions=True)
	doc.proposed_invoice = invoice.name
	doc.save(ignore_permissions=True)
	data = amounts(invoice)
	approval = proposal(
		context,
		"post_completion_invoice",
		{
			"completion_id": name,
			"version": repo.version(doc, job),
			"invoice": invoice.name,
			"invoice_modified": str(invoice.modified),
			"amounts": data,
		},
		RiskClass.FINANCIAL,
	)
	return {"proposal": asdict(approval), "invoice": invoice.name, "due_date": invoice.due_date, **data}


def approve(context, proposal_id, key):
	authorize(context, "invoice")
	digest = retry_key(context, "post_completion_invoice", key)
	previous = frappe.db.get_value(
		repo.COMPLETION,
		{"company": context.company, "invoice_key_hash": digest},
		["name", "invoice_proposal"],
		as_dict=True,
	)
	if previous:
		if previous.invoice_proposal != proposal_id:
			frappe.throw(_("Retry key belongs to another financial approval"))
		return repo.detail(context, previous.name)
	item = load_proposal(context, proposal_id, "post_completion_invoice", RiskClass.FINANCIAL)
	doc, job = repo.document(context, item.arguments["completion_id"], lock=True)
	if doc.invoice_key_hash == digest and doc.invoice_proposal == proposal_id:
		return repo.detail(context, doc.name)
	repo.current(doc, job, item.arguments["version"])
	if (
		doc.status != "Completed"
		or job.docstatus != 1
		or get_datetime(doc.visit_modified) != get_datetime(job.modified)
	):
		frappe.throw(_("Service work is no longer invoice-ready"))
	invoice = invoice_document(doc, lock=True)
	if (
		invoice.docstatus != 0
		or invoice.name != item.arguments["invoice"]
		or str(invoice.modified) != item.arguments["invoice_modified"]
		or amounts(invoice) != item.arguments["amounts"]
	):
		frappe.throw(_("Invoice changed. Review a new financial preview."))
	invoice.flags.ignore_permissions = True
	invoice.submit()
	if amounts(invoice) != item.arguments["amounts"]:
		frappe.throw(_("Invoice pricing changed during posting. Review a new preview."))
	doc.update(
		{
			"status": "Invoiced",
			"invoice": invoice.name,
			"invoice_approved_by": context.user,
			"invoice_proposal": proposal_id,
			"invoice_key_hash": digest,
		}
	)
	doc.save(ignore_permissions=True)
	return repo.detail(context, doc.name)
