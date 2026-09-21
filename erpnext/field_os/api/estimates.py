"""Operator estimate APIs. Every write requires quote capability in the selected company."""

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.customers.frappe_access import ERPNextCustomerAccessPolicy
from erpnext.field_os.estimates import workflow
from erpnext.field_os.estimates.frappe_repository import (
	ESTIMATE,
	document,
	integration,
	recipients,
	stock,
	version,
)
from erpnext.field_os.onboarding.native import price_list as onboarding_price_list
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context
from erpnext.stock.doctype.company_restriction.company_restriction import get_restriction_criterion


def _context(company, capability="quote"):
	context = resolve_tenant_context(company)
	authorize(context, capability)
	return context


@frappe.whitelist()
def list_estimates(company: str, customer_id: str | None = None):
	_context(company, "read")
	filters = {"company": company}
	if customer_id:
		filters["customer"] = customer_id
	return frappe.get_all(
		ESTIMATE,
		filters=filters,
		fields=["name", "customer", "quotation", "status", "modified", "recipient"],
		order_by="modified desc",
		limit=100,
	)


@frappe.whitelist()
def get_estimate(company: str, estimate_id: str):
	_context(company, "read")
	return workflow.detail(company, estimate_id)


@frappe.whitelist()
def options(company: str, customer_id: str):
	_context(company)
	if not ERPNextCustomerAccessPolicy().can_access(company, customer_id):
		frappe.throw(_("Customer is not available in this company"), frappe.PermissionError)
	item = frappe.qb.DocType("Item")
	items = (
		frappe.qb.from_(item)
		.select(item.name, item.item_name, item.is_stock_item, item.standard_rate)
		.where((item.disabled == 0) & (item.is_sales_item == 1))
		.where(get_restriction_criterion("Item", [company]))
		.orderby(item.item_name)
		.limit(500)
		.run(as_dict=True)
	)
	from erpnext.field_os.onboarding.native import config

	return {
		"defaults": config(company, "notifications"),
		"currency": frappe.db.get_value("Company", company, "default_currency"),
		"items": items,
		"recipients": recipients(customer_id),
		"warehouses": frappe.get_all(
			"Warehouse", filters={"company": company, "is_group": 0, "disabled": 0}, pluck="name"
		),
		"integrations": frappe.get_all(
			"Field OS Email Integration",
			filters={"company": company, "enabled": 1},
			fields=["name", "from_address"],
		),
		"tax_templates": frappe.get_all(
			"Sales Taxes and Charges Template", filters={"company": company, "disabled": 0}, pluck="name"
		),
	}


def _lines(company, values):
	if not isinstance(values, list) or not 1 <= len(values) <= 100:
		frappe.throw(_("Choose between 1 and 100 estimate lines"))
	rows = []
	for row in values:
		if not isinstance(row, dict) or set(row) - {"item_code", "qty", "rate", "warehouse"}:
			frappe.throw(_("Estimate lines may only specify item, quantity, rate and warehouse"))
		try:
			qty, rate = Decimal(str(row.get("qty"))), Decimal(str(row.get("rate")))
		except (InvalidOperation, ValueError):
			frappe.throw(_("Quantity and rate must be valid numbers"))
		if (
			not qty.is_finite()
			or not rate.is_finite()
			or not 0 < qty <= 1_000_000
			or not 0 <= rate <= 1_000_000_000
		):
			frappe.throw(_("Quantity must be positive and rate cannot be negative"))
		item = frappe.db.get_value("Item", row.get("item_code"), ["disabled", "is_sales_item"], as_dict=True)
		if not item or item.disabled or not item.is_sales_item:
			frappe.throw(_("Choose an active sales item"))
		stock(company, row["item_code"], row.get("warehouse"))
		rows.append({**row, "qty": float(qty), "rate": float(rate)})
	return rows


@frappe.whitelist(methods=["POST"])
@entitled
def save_estimate(
	company: str,
	customer_id: str,
	values: dict | str,
	estimate_id: str | None = None,
	expected_version: str | None = None,
):
	_context(company)
	values = frappe.parse_json(values)
	if not isinstance(values, dict) or set(values) - {
		"items",
		"recipient",
		"email_integration",
		"valid_until",
		"tax_template",
		"revision_of",
	}:
		frappe.throw(_("Unsupported estimate fields"))
	if not ERPNextCustomerAccessPolicy().can_access(company, customer_id):
		frappe.throw(_("Customer is not available in this company"), frappe.PermissionError)
	if estimate_id:
		doc, quote = document(company, estimate_id, lock=True)
		if (
			doc.customer != customer_id
			or doc.status != "Draft"
			or quote.docstatus
			or version(doc, quote) != expected_version
		):
			frappe.throw(_("Estimate changed or is no longer a draft. Reload before editing."))
	else:
		quote = frappe.get_doc(
			{
				"doctype": "Quotation",
				"company": company,
				"quotation_to": "Customer",
				"party_name": customer_id,
				"transaction_date": nowdate(),
			}
		)
		doc = frappe.get_doc(
			{"doctype": ESTIMATE, "company": company, "customer": customer_id, "status": "Draft"}
		)
		if values.get("revision_of"):
			previous, _quote = document(company, values["revision_of"])
			if previous.customer != customer_id or previous.status not in {"Approved", "Rejected"}:
				frappe.throw(_("Only a decided estimate for this customer can be revised"))
			doc.revision_of = previous.name
	if values.get("recipient", "").strip().lower() not in recipients(customer_id):
		frappe.throw(_("Choose an email address linked to the customer"))
	doc.recipient = values["recipient"].strip().lower()
	doc.email_integration = integration(company, values.get("email_integration")).name
	if not values.get("valid_until") or getdate(values["valid_until"]) < getdate(nowdate()):
		frappe.throw(_("Choose a current estimate expiry date"))
	quote.valid_till = values["valid_until"]
	quote.selling_price_list = (
		frappe.db.get_value("Customer", customer_id, "default_price_list")
		or onboarding_price_list(company)
		or frappe.db.get_single_value("Selling Settings", "selling_price_list")
	)
	price_list = (
		frappe.db.get_value(
			"Price List", {"name": quote.selling_price_list, "enabled": 1, "selling": 1}, "currency"
		)
		if quote.selling_price_list
		else None
	)
	company_currency = frappe.db.get_value("Company", company, "default_currency")
	if not price_list or price_list != company_currency:
		frappe.throw(_("Configure a default selling price list in the company's currency"))
	quote.currency = quote.price_list_currency = company_currency
	quote.conversion_rate = quote.plc_conversion_rate = 1
	quote.set("items", _lines(company, values.get("items")))
	quote.set("taxes", [])
	quote.taxes_and_charges = values.get("tax_template") or None
	if quote.taxes_and_charges:
		if not frappe.db.exists(
			"Sales Taxes and Charges Template",
			{"name": quote.taxes_and_charges, "company": company, "disabled": 0},
		):
			frappe.throw(_("Choose a tax template in the selected company"))
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		quote.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", quote.taxes_and_charges))
	# Field OS quote capability and exact company/customer were verified above.
	quote.save(ignore_permissions=True)
	doc.quotation = quote.name
	doc.save(ignore_permissions=True)
	return workflow.detail(company, doc.name)


@frappe.whitelist(methods=["POST"])
@entitled
def preview_send(company: str, estimate_id: str):
	return workflow.preview(_context(company), estimate_id)


@frappe.whitelist(methods=["POST"])
@entitled
def approve_send(company: str, proposal_id: str, idempotency_key: str):
	return workflow.approve(_context(company), proposal_id, idempotency_key)


@frappe.whitelist(methods=["POST"])
@entitled
def record_decision(
	company: str, estimate_id: str, decision: str, customer_name: str, evidence: str, comment: str = ""
):
	context = _context(company)
	doc, quote = document(company, estimate_id, lock=True)
	return workflow.decide(doc, quote, decision, customer_name, comment, evidence, context.user)


@frappe.whitelist(methods=["POST"])
def customer_decision(token: str, decision: str, customer_name: str, comment: str = ""):
	doc, quote = workflow.customer_document(token, lock=True)
	return workflow.decide(
		doc,
		quote,
		decision,
		customer_name,
		comment,
		"Authenticated recipient used the private approval link delivered to " + doc.recipient,
		frappe.session.user,
	)
