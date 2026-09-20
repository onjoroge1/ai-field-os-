import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSEstimateDecision(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("Estimate decisions are permanent"))
		estimate = frappe.db.get_value(
			"Field OS Estimate", self.field_os_estimate, ["company", "quotation"], as_dict=True
		)
		if not estimate or (estimate.company, estimate.quotation) != (self.company, self.estimate):
			frappe.throw(_("Decision must match the estimate company and quotation"))
