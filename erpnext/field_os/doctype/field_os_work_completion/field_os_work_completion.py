import json

from frappe.model.document import Document


class FieldOSWorkCompletion(Document):
	def validate(self):
		for field in ("checklist_json", "billables_json", "photos_json"):
			json.loads(self.get(field) or "[]")
