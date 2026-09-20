import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, strip_html

from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context


class FieldOSEquipmentNote(Document):
	def validate(self):
		authorize(resolve_tenant_context(self.company), "field_update")
		if not self.is_new():
			frappe.throw(_("Service notes are permanent. Add a new note to record a correction."))
		self.technician = frappe.session.user
		self.occurred_at = now_datetime()
		if not strip_html(self.note or "").strip():
			frappe.throw(_("A service note is required"))
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
		try:
			photos = json.loads(self.photos_json or "[]")
		except (ValueError, TypeError):
			frappe.throw(_("Photos must be a valid JSON list"))
		if (
			not isinstance(photos, list)
			or len(photos) > 20
			or any(not isinstance(photo, str) for photo in photos)
		):
			frappe.throw(_("Photos must be a JSON list of no more than 20 file URLs"))
		for url in photos:
			if not url.startswith("/private/files/") or not frappe.db.exists(
				"File",
				{
					"file_url": url,
					"is_private": 1,
					"attached_to_doctype": "Field OS HVAC Equipment",
					"attached_to_name": self.equipment,
				},
			):
				frappe.throw(
					_("Photos must be private attachments of this equipment"), frappe.PermissionError
				)
