import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSInvoiceNotice(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("Invoice delivery approvals are permanent"))
		if not frappe.db.exists(
			"Field OS Work Completion",
			{"name": self.completion, "company": self.company, "invoice": self.invoice},
		):
			frappe.throw(_("Invoice notice must match its completion and company"))
