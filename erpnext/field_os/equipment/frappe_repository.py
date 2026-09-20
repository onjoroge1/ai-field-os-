"""Company-scoped equipment persistence and Customer 360 reads."""

import json

import frappe
from frappe import _

from erpnext.field_os.adapter.erpnext import ERPNextAdapter
from erpnext.field_os.adapter.types import EquipmentRecord
from erpnext.field_os.equipment.models import EquipmentNote, HVACEquipment

EQUIPMENT = "Field OS HVAC Equipment"
NOTE = "Field OS Equipment Note"
FIELDS = [
	"name",
	"company",
	"customer",
	"site",
	"equipment_name",
	"unit_type",
	"manufacturer",
	"model_number",
	"serial_number",
	"installed_on",
	"warranty_expires_on",
	"parent_equipment",
	"status",
]


def equipment_record(row):
	return HVACEquipment(
		row.name,
		row.company,
		row.customer,
		row.site,
		row.equipment_name,
		row.unit_type,
		row.manufacturer,
		row.model_number,
		row.serial_number,
		row.installed_on,
		row.warranty_expires_on,
		row.parent_equipment,
		row.status,
	)


def note_record(row):
	return EquipmentNote(
		row.name,
		row.company,
		row.equipment,
		row.technician,
		row.note,
		row.occurred_at,
		row.visit,
		tuple(json.loads(row.photos_json or "[]")),
	)


class FrappeEquipmentRepository:
	def list_equipment(self, company, customer_id):
		return [
			equipment_record(row)
			for row in frappe.get_all(
				EQUIPMENT,
				filters={"company": company, "customer": customer_id},
				fields=FIELDS,
				order_by="equipment_name asc, name asc",
				limit_page_length=0,
			)
		]

	def document(self, company, equipment_id):
		if not frappe.db.exists(EQUIPMENT, {"company": company, "name": equipment_id}):
			frappe.throw(_("Equipment is not available in this company"), frappe.PermissionError)
		return frappe.get_doc(EQUIPMENT, equipment_id)

	def get_equipment(self, company, equipment_id):
		return equipment_record(self.document(company, equipment_id))

	def list_notes(self, company, equipment_id):
		return [
			note_record(row)
			for row in frappe.get_all(
				NOTE,
				filters={"company": company, "equipment": equipment_id},
				fields=["*"],
				order_by="occurred_at desc, creation desc",
				limit_page_length=0,
			)
		]

	def create_note(self, company, equipment_id, technician, note, occurred_at, visit_id, photo_urls):
		doc = frappe.get_doc(
			{
				"doctype": NOTE,
				"company": company,
				"equipment": equipment_id,
				"technician": technician,
				"note": note,
				"occurred_at": occurred_at,
				"visit": visit_id,
				"photos_json": json.dumps(photo_urls),
			}
		).insert()
		return note_record(doc)


class CompanyCustomerAdapter(ERPNextAdapter):
	def __init__(self, company):
		self.company = company

	def _get_all(self, doctype, **kwargs):
		if doctype in {"Maintenance Visit", "Quotation", "Sales Invoice"}:
			kwargs["filters"] = {**kwargs.get("filters", {}), "company": self.company}
		return super()._get_all(doctype, **kwargs)

	def list_equipment(self, customer_id):
		return [
			EquipmentRecord(
				item.id, item.customer_id, item.name, item.serial_number or "", item.warranty_expires_on
			)
			for item in FrappeEquipmentRepository().list_equipment(self.company, customer_id)
		]
