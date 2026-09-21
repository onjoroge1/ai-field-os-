import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSBillingEvent(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("Billing events are permanent"))

	def on_trash(self):
		frappe.throw(_("Billing events are permanent"))
