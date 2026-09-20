"""Native company setup, owner isolation and operational effects of configured hours and skills."""

import unittest
from datetime import datetime, timedelta

import frappe

from erpnext.field_os.api import onboarding
from erpnext.field_os.onboarding import native
from erpnext.field_os.security.authorization import CapabilityDenied
from erpnext.field_os.tests.integration.test_agreements_live import prepare_agreements
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B, MANAGER, OTHER

OWNER = "fieldos-owner@example.invalid"
NEW_TECH = "setup-technician@example.invalid"


def prepare_onboarding():
	prepare_agreements()
	frappe.set_user("Administrator")
	frappe.reload_doc("field_os", "doctype", "field_os_onboarding")
	if not frappe.db.exists("User", OWNER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": OWNER,
				"first_name": "FieldOS Owner",
				"send_welcome_email": 0,
				"user_type": "System User",
				"roles": [{"role": "Field OS Owner"}],
			}
		).insert()
	if not frappe.db.exists("User Permission", {"user": OWNER, "allow": "Company", "for_value": COMPANY_A}):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": OWNER,
				"allow": "Company",
				"for_value": COMPANY_A,
				"apply_to_all_doctypes": 1,
			}
		).insert()
	frappe.defaults.set_user_default("company", COMPANY_A, OWNER)
	import os

	if os.environ.get("FIELD_OS_TEST_PASSWORD"):
		from frappe.utils.password import update_password

		update_password(OWNER, os.environ["FIELD_OS_TEST_PASSWORD"])


class LiveOnboarding(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare_onboarding()

	def setUp(self):
		frappe.db.savepoint("onboarding_test")
		frappe.set_user(OWNER)
		self.state = onboarding.get_setup(COMPANY_A)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="onboarding_test")
		frappe.clear_cache()

	def save(self, step, values):
		self.state = onboarding.save_step(COMPANY_A, step, values, self.state["version"])
		return self.state

	def company(self):
		return self.save(
			"company",
			{
				"locations": [
					{
						"name": "Boston shop",
						"address_line1": "100 Test Street",
						"city": "Boston",
						"country": "United States",
					}
				],
				"days": [0, 1, 2, 3, 4],
				"opens": "08:00",
				"closes": "18:00",
			},
		)

	def user(self):
		return self.save(
			"users",
			{
				"email": NEW_TECH,
				"first_name": "Avery",
				"role": "Field OS Technician",
				"password": "acceptance-password-42!",
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2020-01-01",
				"skills": ["Heating"],
			},
		)

	def test_new_company_requires_system_manager_and_has_native_accounts(self):
		with self.assertRaises(frappe.PermissionError):
			onboarding.create_company("FieldOS Setup New", "FSN", "United States", "USD")
		frappe.set_user("Administrator")
		result = onboarding.create_company("FieldOS Setup New", "FSN", "United States", "USD")
		company = frappe.get_doc("Company", result["company"])
		self.assertTrue(company.default_income_account)
		self.assertTrue(company.default_receivable_account)
		self.assertTrue(frappe.db.exists("Warehouse", {"company": company.name}))
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.PermissionError):
			onboarding.get_setup(company.name)

	def test_complete_setup_creates_native_records_and_enforces_hours_and_skills(self):
		self.company()
		self.user()
		self.save(
			"users",
			{
				"email": NEW_TECH,
				"first_name": "Avery",
				"role": "Field OS Technician",
				"skills": ["Heating", "Cooling"],
			},
		)
		self.assertIn("Employee", frappe.get_roles(NEW_TECH))
		self.save("services", [{"name": "Heating tune-up", "rate": 125, "skill": "Heating"}])
		self.save("notifications", {"preferred_channel": "None", "invoice_due_days": 14})
		completed = onboarding.complete(COMPANY_A, self.state["version"])
		self.assertEqual(completed["status"], "Completed")
		item = frappe.get_doc("Item", completed["services"][0]["item"])
		self.assertEqual({r.company for r in item.allowed_companies}, {COMPANY_A})
		self.assertEqual(item.standard_rate, 125)
		self.assertTrue(frappe.db.exists("Address", completed["profile"]["locations"][0]["address"]))
		frappe.set_user(NEW_TECH)
		self.assertEqual(native.resolve_tenant_context(COMPANY_A).company, COMPANY_A)
		with self.assertRaises(frappe.PermissionError):
			native.resolve_tenant_context(COMPANY_B)
		frappe.set_user(OWNER)
		start = datetime(2030, 1, 7, 9)
		person = completed["users"][0]["technician"]
		native.check_schedule(COMPANY_A, person, start, start + timedelta(hours=2), [item.name])
		with self.assertRaises(frappe.ValidationError):
			native.check_schedule(
				COMPANY_A, person, start.replace(hour=19), start.replace(hour=21), [item.name]
			)
		with self.assertRaises(frappe.ValidationError):
			native.check_schedule(COMPANY_A, "unqualified", start, start + timedelta(hours=2), [item.name])

	def test_owner_and_native_record_boundaries_stale_updates_and_privilege_escalation(self):
		self.company()
		with self.assertRaises(frappe.TimestampMismatchError):
			onboarding.save_step(COMPANY_A, "notifications", {"preferred_channel": "None"}, "new")
		with self.assertRaises(frappe.ValidationError):
			self.save(
				"users", {"email": "bad@example.invalid", "first_name": "Bad", "role": "System Manager"}
			)
		with self.assertRaises(frappe.PermissionError):
			self.save("users", {"email": OTHER, "first_name": "Other", "role": "Field OS Owner"})
		name = frappe.db.get_value(native.DOCTYPE, {"company": COMPANY_A}, "name")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(native.DOCTYPE, name).save()
		frappe.set_user(MANAGER)
		with self.assertRaises(CapabilityDenied):
			onboarding.get_setup(COMPANY_A)
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(native.DOCTYPE, pluck="name")

	def test_setup_cannot_finish_with_unqualified_services_or_missing_selected_channel(self):
		with self.assertRaises(frappe.ValidationError):
			onboarding.complete(COMPANY_A, self.state["version"])
		self.company()
		self.user()
		self.save("services", [{"name": "Chiller maintenance", "rate": 175, "skill": "Chillers"}])
		self.save("notifications", {"preferred_channel": "Email", "invoice_due_days": 30})
		checks = {row["key"]: row for row in onboarding.get_setup(COMPANY_A)["checks"]}
		self.assertFalse(checks["skills"]["ok"])
		self.assertFalse(checks["email"]["ok"])
		with self.assertRaises(frappe.ValidationError):
			onboarding.complete(COMPANY_A, self.state["version"])


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveOnboarding)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Onboarding live acceptance checks failed")
	return {"passed": result.testsRun}
