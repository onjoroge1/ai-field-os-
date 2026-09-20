import json

from frappe.model.document import Document


class FieldOSMigrationBatch(Document):
	def validate(self):
		json.loads(self.rows_json)
		json.loads(self.created_records_json or "[]")
