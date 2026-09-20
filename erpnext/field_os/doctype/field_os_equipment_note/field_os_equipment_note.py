import json

import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSEquipmentNote(Document):
	def validate(self):
		equipment = frappe.db.get_value(
			"Field OS HVAC Equipment", self.equipment, ["company", "customer"], as_dict=True
		)
		if not equipment or equipment.company != self.company:
			frappe.throw(_("Equipment note must match the equipment tenant"))
		if self.visit:
			visit = frappe.db.get_value(
				"Maintenance Visit", self.visit, ["company", "customer"], as_dict=True
			)
			if not visit or (visit.company, visit.customer) != (self.company, equipment.customer):
				frappe.throw(_("Equipment note visit must belong to the same tenant and customer"))
		photos = json.loads(self.photos_json or "[]")
		if (
			not isinstance(photos, list)
			or len(photos) > 20
			or any(not isinstance(photo, str) for photo in photos)
		):
			frappe.throw(_("Photos must be a JSON list of no more than 20 file URLs"))
