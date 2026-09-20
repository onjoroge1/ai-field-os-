from frappe.model.document import Document

from erpnext.field_os.completions.repository import validate_document


class FieldOSWorkCompletion(Document):
	def validate(self):
		validate_document(self)
