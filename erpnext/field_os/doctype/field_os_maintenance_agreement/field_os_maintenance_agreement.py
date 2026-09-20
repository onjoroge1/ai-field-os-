from frappe.model.document import Document

from erpnext.field_os.agreements.frappe_repository import generate_visits, validate_agreement


class FieldOSMaintenanceAgreement(Document):
	def validate(self):
		validate_agreement(self)

	def on_update(self):
		if self.status == "Active":
			generate_visits(self)
