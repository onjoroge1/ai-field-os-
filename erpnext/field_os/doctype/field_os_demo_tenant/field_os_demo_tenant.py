import json

from frappe.model.document import Document


class FieldOSDemoTenant(Document):
	def validate(self):
		json.loads(self.manifest_json or "[]")
