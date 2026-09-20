import json

import frappe
from frappe.model.document import Document


class FieldOSEquipmentNote(Document):
	def validate(self):
		if frappe.db.get_value("Field OS HVAC Equipment", self.equipment, "company") != self.company:
			frappe.throw("Equipment note must match the equipment tenant")
		json.loads(self.photos_json or "[]")
