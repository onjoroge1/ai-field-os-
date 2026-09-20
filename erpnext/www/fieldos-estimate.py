import frappe
from frappe.utils import strip_html

from erpnext.field_os.estimates.workflow import token_document

no_cache = 1


def get_context(context):
	doc, quote = token_document(frappe.form_dict.get("token"))
	context.no_cache = 1
	context.title = "Review estimate"
	context.estimate = doc
	context.quotation = quote
	context.line_items = [
		dict(description=strip_html(row.description), qty=row.qty, amount=row.amount) for row in quote.items
	]
	context.token = frappe.form_dict.token
