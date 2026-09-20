from datetime import date
from unittest import TestCase

from erpnext.field_os.equipment.models import EquipmentNote, HVACEquipment
from erpnext.field_os.equipment.service import EquipmentService
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class Repo:
	def __init__(self):
		self.parent = HVACEquipment(
			"E1", "CO", "C1", "S1", "Heat pump", "Heat Pump", warranty_expires_on=date(2030, 1, 1)
		)
		self.child = HVACEquipment("E2", "CO", "C1", "S1", "Thermostat", "Thermostat", parent_id="E1")
		self.notes = []

	def list_equipment(self, company, customer_id):
		return [x for x in (self.parent, self.child) if x.company == company]

	def get_equipment(self, company, equipment_id):
		item = {"E1": self.parent, "E2": self.child}[equipment_id]
		if item.company != company:
			raise ValueError("not found")
		return item

	def list_notes(self, company, equipment_id):
		return self.notes

	def create_note(self, company, equipment_id, technician, note, occurred_at, visit_id, photo_urls):
		item = EquipmentNote("N1", company, equipment_id, technician, note, occurred_at, visit_id, photo_urls)
		self.notes.append(item)
		return item


class TestEquipment(TestCase):
	def test_hierarchy_notes_and_tenant_scope(self):
		repo = Repo()
		manager = TenantContext("CO", "m", frozenset({FieldOSRole.MANAGER}))
		tech = TenantContext("CO", "t", frozenset({FieldOSRole.TECHNICIAN}))
		self.assertEqual(EquipmentService(repo).history(manager, "E2").ancestors[0].id, "E1")
		note = EquipmentService(repo).add_note(tech, "E1", "Replaced contactor", "V1", ("/files/a.jpg",))
		self.assertEqual(note.photo_urls, ("/files/a.jpg",))
		with self.assertRaises(ValueError):
			EquipmentService(repo).history(
				TenantContext("OTHER", "m", frozenset({FieldOSRole.MANAGER})), "E1"
			)
