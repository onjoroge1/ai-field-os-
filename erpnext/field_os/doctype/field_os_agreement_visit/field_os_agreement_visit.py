import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from erpnext.field_os.agreements.frappe_repository import document


class FieldOSAgreementVisit(Document):
	def validate(self):
		agreement = document(self.company, self.agreement)
		previous = self.get_doc_before_save()
		if previous and any(
			str(self.get(k)) != str(previous.get(k)) for k in ("company", "agreement", "due_on")
		):
			frappe.throw(_("Recurring visit ownership and due date cannot change"))
		if not getdate(agreement.starts_on) < getdate(self.due_on) <= getdate(agreement.ends_on):
			frappe.throw(_("Visit must fall within the agreement term"))
		if self.maintenance_visit:
			if not frappe.db.exists(
				"Maintenance Visit",
				{
					"name": self.maintenance_visit,
					"company": self.company,
					"customer": agreement.customer,
					"customer_address": agreement.site,
				},
			):
				frappe.throw(_("Service visit must belong to the same agreement customer and site"))
