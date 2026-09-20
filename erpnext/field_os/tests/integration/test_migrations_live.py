"""Native CSV imports, tenant isolation, atomic failure and safe destructive rollback."""

import unittest
from unittest.mock import patch

import frappe

from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.api import migrations
from erpnext.field_os.customers.frappe_access import ERPNextCustomerAccessPolicy
from erpnext.field_os.migrations import native
from erpnext.field_os.security.authorization import CapabilityDenied
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B, MANAGER, OTHER
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER, prepare_onboarding

CUSTOMERS = "customer_id,customer_name,email,phone\nc1,Migration Avery,avery@example.invalid,5550100\n"
SITES = "site_id,customer_id,title,address_line1,city,state,postal_code\ns1,c1,Avery shop,1 Test Road,Boston,MA,02110\n"
EQUIPMENT = "equipment_id,customer_id,site_id,equipment_name,unit_type,model_number,serial_number,installed_on\ne1,c1,s1,Imported heat pump,Heat pump,M1,S1,2020-01-01\n"


def prepare_migrations():
	prepare_onboarding()
	for name in ("field_os_migration_batch", "field_os_migration_record"):
		frappe.reload_doc("field_os", "doctype", name)


class LiveMigrations(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare_migrations()

	def setUp(self):
		frappe.db.savepoint("migration_test")
		frappe.set_user(OWNER)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="migration_test")
		frappe.clear_cache()

	def apply(self, kind, content):
		batch = migrations.validate_csv(COMPANY_A, kind, content)
		self.assertEqual(batch["status"], "Validated", batch["error_report"])
		batch = migrations.apply(COMPANY_A, batch["name"], batch["version"])
		self.assertEqual(batch["status"], "Applied", batch["error_report"])
		return batch

	def rollback(self, batch, key="rollback-acceptance"):
		preview = migrations.preview_rollback(COMPANY_A, batch["name"])
		return migrations.approve_rollback(COMPANY_A, preview["proposal"]["id"], key)

	def test_dry_run_validation_and_native_customer_site_equipment_chain(self):
		before = frappe.db.count("Customer")
		preview = migrations.validate_csv(COMPANY_A, "customers", CUSTOMERS)
		self.assertEqual(frappe.db.count("Customer"), before)
		customers = migrations.apply(COMPANY_A, preview["name"], preview["version"])
		self.assertEqual(customers["status"], "Applied", customers["error_report"])
		customer = native.mapping(COMPANY_A, "customers", "c1").target_name
		self.assertTrue(ERPNextCustomerAccessPolicy().can_access(COMPANY_A, customer))
		self.assertFalse(ERPNextCustomerAccessPolicy().can_access(COMPANY_B, customer))
		self.assertEqual(frappe.get_doc("Customer", customer).email_id, "avery@example.invalid")
		self.assertEqual(migrations.apply(COMPANY_A, preview["name"], "old")["name"], preview["name"])
		self.assertEqual(frappe.db.count("Customer"), before + 1)
		self.apply("sites", SITES)
		self.apply("equipment", EQUIPMENT)
		unit = frappe.get_doc(
			"Field OS HVAC Equipment", native.mapping(COMPANY_A, "equipment", "e1").target_name
		)
		self.assertEqual(unit.customer, customer)
		self.assertEqual(unit.site, native.mapping(COMPANY_A, "sites", "s1").target_name)
		duplicate = migrations.validate_csv(COMPANY_A, "customers", CUSTOMERS)
		self.assertEqual(duplicate["status"], "Failed Validation")

	def test_invalid_references_error_csv_and_cross_tenant_boundaries(self):
		bad = migrations.validate_csv(COMPANY_A, "sites", SITES)
		self.assertEqual(bad["status"], "Failed Validation")
		self.assertIn("customer_id", bad["error_report"])
		formula = migrations.validate_csv(COMPANY_A, "customers", "customer_id,customer_name\n=cmd,\n")
		self.assertIn("'=cmd", formula["error_report"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(native.BATCH, bad["name"]).save()
		frappe.set_user(MANAGER)
		with self.assertRaises(CapabilityDenied):
			migrations.get_batch(COMPANY_A, bad["name"])
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			migrations.get_batch(COMPANY_A, bad["name"])

	def test_native_apply_failure_is_atomic_and_audited(self):
		content = CUSTOMERS + "c2,Second Customer,second@example.invalid,5550200\n"
		batch = migrations.validate_csv(COMPANY_A, "customers", content)
		before = frappe.db.count("Customer")
		create = native.create_record

		def fail_second(ctx, doc, row):
			if row["number"] == 3:
				raise frappe.ValidationError("Simulated native rejection after the first real insert")
			return create(ctx, doc, row)

		with patch.object(native, "create_record", side_effect=fail_second):
			result = migrations.apply(COMPANY_A, batch["name"], batch["version"])
		self.assertEqual(result["status"], "Apply Failed")
		self.assertEqual(frappe.db.count("Customer"), before)
		self.assertFalse(native.mapping(COMPANY_A, "customers", "c1"))
		self.assertFalse(native.mapping(COMPANY_A, "customers", "c2"))

	def test_rollback_blocks_dependencies_then_removes_exact_records_and_retries_durably(self):
		customers = self.apply("customers", CUSTOMERS)
		sites = self.apply("sites", SITES)
		equipment = self.apply("equipment", EQUIPMENT)
		with self.assertRaises(frappe.ValidationError):
			self.rollback(customers)
		with self.assertRaises(frappe.ValidationError):
			self.rollback(sites)
		self.assertTrue(native.mapping(COMPANY_A, "sites", "s1"))
		self.assertEqual(self.rollback(equipment, "equipment")["status"], "Rolled Back")
		self.assertEqual(self.rollback(sites, "sites")["status"], "Rolled Back")
		preview = migrations.preview_rollback(COMPANY_A, customers["name"])
		pid = preview["proposal"]["id"]
		result = migrations.approve_rollback(COMPANY_A, pid, "customers")
		self.assertEqual(result["status"], "Rolled Back")
		for record in customers["records"]:
			self.assertFalse(frappe.db.exists(record["doctype"], record["name"]))
		FrappeCacheProposalStore().delete(COMPANY_A, pid)
		self.assertEqual(migrations.approve_rollback(COMPANY_A, pid, "customers")["name"], result["name"])

	def test_modified_records_and_new_comments_are_never_rolled_back(self):
		batch = self.apply("customers", CUSTOMERS)
		name = native.mapping(COMPANY_A, "customers", "c1").target_name
		preview = migrations.preview_rollback(COMPANY_A, batch["name"])
		frappe.db.set_value(
			"Customer", name, "customer_name", "Operator corrected the name", update_modified=False
		)
		with self.assertRaises(frappe.ValidationError):
			migrations.approve_rollback(COMPANY_A, preview["proposal"]["id"], "changed")
		frappe.db.set_value("Customer", name, "customer_name", "Migration Avery", update_modified=False)
		frappe.get_doc("Customer", name).add_comment("Comment", "Operator called this customer")
		with self.assertRaises(frappe.ValidationError):
			migrations.preview_rollback(COMPANY_A, batch["name"])


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveMigrations)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Migration live acceptance checks failed")
	return {"passed": result.testsRun}
