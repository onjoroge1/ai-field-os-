from urllib.parse import quote as urlquote

import frappe
from frappe.utils import strip_html

from erpnext.field_os.estimates.workflow import customer_document

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.title = "Review estimate"
	if frappe.session.user == "Guest":
		target = "/fieldos-estimate?token=" + urlquote(frappe.form_dict.get("token") or "", safe="")
		context.login_url = "/login?redirect-to=" + urlquote(target, safe="")
		return
	doc, quote = customer_document(frappe.form_dict.get("token"))
	context.estimate = doc
	context.quotation = quote
	context.line_items = [
		dict(
			description=strip_html(row.description or row.item_name or row.item_code),
			qty=row.qty,
			amount=row.amount,
		)
		for row in quote.items
	]
	context.token = frappe.form_dict.token
