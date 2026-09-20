"""Real-site acceptance checks. Run only on a disposable site with allow_tests=1.

bench --site test_site execute erpnext.field_os.tests.live_equipment.run
Uses native documents and real permissions; no mocked database or permission calls.
"""

import base64
import io
import json
import unittest

import frappe
from PIL import Image

from erpnext.field_os.api import equipment
from erpnext.field_os.api.customers import customer_360
from erpnext.field_os.api.operator import global_search
from erpnext.field_os.equipment.frappe_repository import EQUIPMENT, NOTE
from erpnext.field_os.security.authorization import CapabilityDenied

COMPANY_A = "FieldOS Integration A"
COMPANY_B = "FieldOS Integration B"
TECH = "fieldos-tech@example.invalid"
MANAGER = "fieldos-manager@example.invalid"
OTHER = "fieldos-other@example.invalid"


def prepare():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	if not frappe.db.exists("Warehouse Type", "Transit"):
		from erpnext.setup.setup_wizard.operations.install_fixtures import install

		install("United States")
	for label, abbr in ((COMPANY_A, "FIA"), (COMPANY_B, "FIB")):
		if not frappe.db.exists("Company", label):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": label,
					"abbr": abbr,
					"country": "United States",
					"default_currency": "USD",
					"chart_of_accounts": "Standard",
					"enable_perpetual_inventory": 0,
				}
			).insert()
	for doctype, field, label in (
		("Customer Group", "customer_group_name", "All Customer Groups"),
		("Territory", "territory_name", "All Territories"),
		("Item Group", "item_group_name", "All Item Groups"),
	):
		if not frappe.db.exists(doctype, label):
			frappe.get_doc({"doctype": doctype, field: label, "is_group": 1}).insert()
	if not frappe.db.exists("Customer", "FieldOS Shared Customer"):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "FieldOS Shared Customer",
				"customer_type": "Company",
				"customer_group": "Commercial",
				"territory": "All Territories",
			}
		).insert()
	customer = frappe.db.get_value("Customer", {"customer_name": "FieldOS Shared Customer"}, "name")
	if not frappe.db.exists("Address", {"address_title": "FieldOS Service Site"}):
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "FieldOS Service Site",
				"address_type": "Billing",
				"address_line1": "100 Test Street",
				"city": "Boston",
				"country": "United States",
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert()
	site = frappe.db.get_value("Address", {"address_title": "FieldOS Service Site"}, "name")
	for company in (COMPANY_A, COMPANY_B):
		if not frappe.db.exists("Issue", {"company": company, "customer": customer}):
			frappe.get_doc(
				{
					"doctype": "Issue",
					"subject": "FieldOS service request",
					"company": company,
					"customer": customer,
				}
			).insert()
	for user, role, company in (
		(TECH, "Field OS Technician", COMPANY_A),
		(MANAGER, "Field OS Manager", COMPANY_A),
		(OTHER, "Field OS Technician", COMPANY_B),
	):
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": user.split("@")[0],
					"send_welcome_email": 0,
					"user_type": "System User",
					"roles": [{"role": role}],
				}
			).insert()
		if not frappe.db.exists("User Permission", {"user": user, "allow": "Company", "for_value": company}):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": user,
					"allow": "Company",
					"for_value": company,
					"apply_to_all_doctypes": 1,
				}
			).insert()
		frappe.defaults.set_user_default("company", company, user)
	return customer, site


class LiveEquipment(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.customer, cls.site = prepare()
		# Master setup may commit (Company, User). Each actual test uses a savepoint.
		frappe.db.commit()

	def setUp(self):
		frappe.set_user(MANAGER)
		frappe.db.savepoint("equipment_test")
		self.parent = self.create("Rooftop heat pump")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="equipment_test")
		frappe.clear_cache()

	def create(self, name, **values):
		return equipment.save_equipment(
			COMPANY_A, self.customer, self.site, {"equipment_name": name, "unit_type": "Heat pump", **values}
		)["name"]

	def test_create_read_edit_and_stale_version(self):
		state = equipment.history(COMPANY_A, self.parent)
		self.assertEqual(state["equipment"]["name"], "Rooftop heat pump")
		equipment.save_equipment(
			COMPANY_A, self.customer, self.site, {"serial_number": "SN-123"}, self.parent, state["modified"]
		)
		self.assertEqual(equipment.history(COMPANY_A, self.parent)["equipment"]["serial_number"], "SN-123")
		with self.assertRaises(frappe.TimestampMismatchError):
			equipment.save_equipment(
				COMPANY_A,
				self.customer,
				self.site,
				{"serial_number": "stale"},
				self.parent,
				state["modified"],
			)

	def test_hierarchy_and_cycle_validation(self):
		child = self.create("Thermostat", parent_equipment=self.parent)
		self.assertEqual(equipment.history(COMPANY_A, child)["ancestors"][0]["id"], self.parent)
		self.assertEqual(equipment.history(COMPANY_A, self.parent)["children"][0]["id"], child)
		state = equipment.history(COMPANY_A, self.parent)
		with self.assertRaises(frappe.ValidationError):
			equipment.save_equipment(
				COMPANY_A,
				self.customer,
				self.site,
				{"parent_equipment": child},
				self.parent,
				state["modified"],
			)

	def test_technician_history_and_immutable_note(self):
		frappe.set_user(TECH)
		note = equipment.add_note(COMPANY_A, self.parent, "Replaced contactor")
		self.assertEqual(note["technician"], TECH)
		self.assertEqual(equipment.history(COMPANY_A, self.parent)["notes"][0]["note"], "Replaced contactor")
		with self.assertRaises(CapabilityDenied):
			self.create("Unauthorized edit")
		frappe.set_user("Administrator")
		doc = frappe.get_doc(NOTE, note["id"])
		doc.note = "Rewrite history"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_company_boundary_on_api_and_native_records(self):
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			equipment.history(COMPANY_A, self.parent)
		with self.assertRaises(frappe.PermissionError):
			equipment.history(COMPANY_B, self.parent)
		self.assertFalse(frappe.has_permission(EQUIPMENT, "read", doc=self.parent))
		self.assertFalse(frappe.get_list(EQUIPMENT, filters={"name": self.parent}))
		with self.assertRaises(frappe.PermissionError):
			equipment.add_note(COMPANY_B, self.parent, "Wrong tenant")

	def test_private_photo_and_native_file_access(self):
		frappe.set_user(TECH)
		data = io.BytesIO()
		Image.new("RGB", (5, 5), "blue").save(data, format="PNG")
		url = equipment.upload_photo(COMPANY_A, self.parent, base64.b64encode(data.getvalue()).decode())[
			"file_url"
		]
		self.assertTrue(url.startswith("/private/files/"))
		equipment.add_note(COMPANY_A, self.parent, "Inspection photo", photo_urls=[url])
		file = frappe.get_doc("File", {"file_url": url, "attached_to_name": self.parent})
		self.assertTrue(file.has_permission("read"))
		frappe.set_user(OTHER)
		self.assertFalse(file.has_permission("read"))

	def test_untrusted_photos_are_rejected(self):
		frappe.set_user(TECH)
		for url in ("https://example.com/photo.jpg", "/files/public.jpg", "/private/files/unknown.jpg"):
			with self.subTest(url=url), self.assertRaises(frappe.PermissionError):
				equipment.add_note(COMPANY_A, self.parent, "Invalid photo", photo_urls=[url])
		with self.assertRaises(frappe.ValidationError):
			equipment.upload_photo(COMPANY_A, self.parent, base64.b64encode(b"not an image").decode())

	def test_customer_360_and_search_find_equipment_without_invoice(self):
		frappe.set_user(TECH)
		result = customer_360(COMPANY_A, self.customer)
		self.assertIn(self.parent, [item["id"] for item in result["hvac_equipment"]])
		self.assertIn(
			self.customer,
			[
				item["record"]["record_id"]
				for item in global_search(COMPANY_A, "FieldOS Shared")
				if item["kind"] == "customer"
			],
		)

	def test_shared_customer_history_is_scoped_to_company(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Sales Person", "FieldOS Technician"):
			frappe.get_doc(
				{
					"doctype": "Sales Person",
					"sales_person_name": "FieldOS Technician",
					"parent_sales_person": "Sales Team",
				}
			).insert()
		visits = {}
		for company in (COMPANY_A, COMPANY_B):
			visits[company] = (
				frappe.get_doc(
					{
						"doctype": "Maintenance Visit",
						"company": company,
						"customer": self.customer,
						"completion_status": "Fully Completed",
						"maintenance_type": "Unscheduled",
						"purposes": [{"service_person": "FieldOS Technician", "work_done": "Inspected unit"}],
					}
				)
				.insert()
				.name
			)
		frappe.set_user(TECH)
		view = customer_360(COMPANY_A, self.customer)
		self.assertIn(visits[COMPANY_A], [event["record_id"] for event in view["timeline"]])
		self.assertNotIn(visits[COMPANY_B], [event["record_id"] for event in view["timeline"]])
		with self.assertRaises(frappe.ValidationError):
			equipment.add_note(COMPANY_A, self.parent, "Wrong visit", visit_id=visits[COMPANY_B])

	def test_native_update_cannot_move_equipment_to_other_company(self):
		frappe.set_user("Administrator")
		doc = frappe.get_doc(EQUIPMENT, self.parent)
		doc.company = COMPANY_B
		with self.assertRaises(frappe.ValidationError):
			doc.save()


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveEquipment)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Equipment live acceptance checks failed")
	return {"passed": result.testsRun}
