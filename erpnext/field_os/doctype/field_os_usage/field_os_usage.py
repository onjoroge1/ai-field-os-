import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSUsage(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("Usage records are permanent"))

	def on_trash(self):
		frappe.throw(_("Usage records are permanent"))
