import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSMaintenanceAgreement(Document):
	def validate(self):
		if self.ends_on <= self.starts_on:
			frappe.throw(_("End date must follow start date"))
		if not 1 <= self.interval_months <= 60:
			frappe.throw(_("Interval must be 1-60 months"))
