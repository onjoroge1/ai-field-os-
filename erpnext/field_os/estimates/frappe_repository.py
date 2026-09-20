"""Native quotations with a company-scoped Field OS approval lifecycle."""

import hashlib
from decimal import Decimal

import frappe
from frappe import _

from erpnext.field_os.estimates.models import Estimate, EstimateLine

ESTIMATE = "Field OS Estimate"
DECISION = "Field OS Estimate Decision"


def document(company, name, *, lock=False):
	if not frappe.db.exists(ESTIMATE, {"name": name, "company": company}):
		frappe.throw(_("Estimate is not available in this company"), frappe.PermissionError)
	if lock:
		frappe.db.get_value(ESTIMATE, name, "name", for_update=True)
	doc = frappe.get_doc(ESTIMATE, name)
	if lock:
		frappe.db.get_value("Quotation", doc.quotation, "name", for_update=True)
	quote = frappe.get_doc("Quotation", doc.quotation)
	if (quote.company, quote.quotation_to, quote.party_name) != (company, "Customer", doc.customer):
		frappe.throw(_("Quotation and estimate ownership do not match"), frappe.PermissionError)
	return doc, quote


def version(doc, quote):
	return hashlib.sha256(f"{doc.modified}:{quote.modified}:{quote.docstatus}".encode()).hexdigest()


def recipients(customer):
	addresses = {frappe.db.get_value("Customer", customer, "email_id")}
	contacts = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": customer},
		pluck="parent",
	)
	if contacts:
		addresses.update(
			frappe.get_all("Contact Email", filters={"parent": ["in", contacts]}, pluck="email_id")
		)
	return sorted({address.strip().lower() for address in addresses if address})


def integration(company, name):
	row = frappe.db.get_value(
		"Field OS Email Integration",
		{"name": name, "company": company, "enabled": 1},
		["name", "from_address"],
		as_dict=True,
	)
	if not row or not frappe.db.exists("Email Account", {"email_id": row.from_address, "enable_outgoing": 1}):
		frappe.throw(_("Configure an enabled company email integration with an outgoing Email Account"))
	return row


def stock(company, item_code, warehouse):
	item = frappe.db.get_value(
		"Item", item_code, ["is_stock_item", "disabled", "is_sales_item"], as_dict=True
	)
	if not item:
		frappe.throw(_("Item does not exist"))
	if warehouse and not frappe.db.exists(
		"Warehouse", {"name": warehouse, "company": company, "is_group": 0}
	):
		frappe.throw(_("Warehouse must belong to the selected company"))
	if not item.is_stock_item:
		return None
	if not warehouse or not frappe.db.exists(
		"Warehouse", {"name": warehouse, "company": company, "is_group": 0, "disabled": 0}
	):
		frappe.throw(_("Stock parts require a warehouse in the selected company"))
	quantity = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
	return Decimal(str(quantity or 0))


class FrappeEstimateRepository:
	stock = staticmethod(stock)

	def get(self, company, estimate_id):
		doc, quote = document(company, estimate_id)
		return Estimate(
			doc.name,
			company,
			doc.customer,
			doc.status,
			quote.currency,
			quote.valid_till,
			tuple(
				EstimateLine(
					row.item_code,
					row.description,
					Decimal(str(row.qty)),
					Decimal(str(row.rate)),
					row.warehouse,
				)
				for row in quote.items
			),
			version(doc, quote),
		)

	def set_status(self, company, estimate_id, status, version):
		# Changes must go through the audited, durable native workflow.
		raise RuntimeError("Use the native estimate workflow to send or record a decision")
