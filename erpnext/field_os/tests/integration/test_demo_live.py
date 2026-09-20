"""Seed real HVAC records and reset without touching posted or production accounting."""

import os
import unittest

import frappe
from frappe.utils import add_days, nowdate

from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.api import demo, email, sms
from erpnext.field_os.demo import native
from erpnext.field_os.demo.safety import block_delivery
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B
from erpnext.field_os.tests.integration.test_migrations_live import prepare_migrations
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER

PASSWORD = "synthetic-demo-acceptance-42!"


def prepare_demo():
	prepare_migrations()
	frappe.reload_doc("field_os", "doctype", "field_os_demo_tenant")
	frappe.defaults.set_user_default("company", COMPANY_A, "Administrator")
	if os.environ.get("FIELD_OS_TEST_PASSWORD"):
		from frappe.utils.password import update_password

		update_password("Administrator", os.environ["FIELD_OS_TEST_PASSWORD"])


class LiveDemo(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare_demo()
		cls.seed = demo.create("Northstar HVAC", PASSWORD, "native-demo-fixture")

	def setUp(self):
		frappe.db.savepoint("demo_test")
		frappe.set_user("Administrator")

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="demo_test")
		frappe.clear_cache()

	def test_real_dataset_native_guides_and_idempotent_seed(self):
		data = demo.create("Northstar HVAC", PASSWORD, "native-demo-fixture")
		self.assertEqual(data["company"], self.seed["company"])
		company, manifest = data["company"], data["manifest"]
		self.assertEqual(data["status"], "Ready")
		self.assertEqual(len(data["scenarios"]), 3)
		self.assertEqual(frappe.db.count("Field OS HVAC Equipment", {"company": company}), 3)
		self.assertTrue(frappe.db.exists("Maintenance Visit", {"company": company, "name": manifest["job"]}))
		self.assertEqual(frappe.db.get_value("Field OS Estimate", manifest["estimate"], "status"), "Approved")
		self.assertEqual(
			frappe.db.get_value("Field OS Communication Thread", manifest["thread"], "company"), company
		)
		frappe.set_user(manifest["users"][0]["email"])
		self.assertEqual(demo.get_demo(company)["company"], company)
		with self.assertRaises(frappe.PermissionError):
			demo.get_demo(COMPANY_B)

	def test_production_reset_and_owner_provisioning_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			demo.preview_reset(COMPANY_A)
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.PermissionError):
			demo.create("Bad tenant", PASSWORD, "unauthorized")
		with self.assertRaises(frappe.PermissionError):
			demo.preview_reset(self.seed["company"])

	def test_all_field_os_sends_and_native_invoice_email_are_blocked(self):
		company = self.seed["company"]
		for method in (email.approve_send, sms.approve_send):
			with self.assertRaises(frappe.ValidationError):
				method(company, "not-needed", "not-needed", "not-needed")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Email Queue",
					"sender": "demo@example.invalid",
					"message": "Synthetic only",
					"recipients": [{"recipient": "someone@example.invalid"}],
					"reference_doctype": "Field OS Estimate",
					"reference_name": self.seed["manifest"]["estimate"],
				}
			).insert(ignore_permissions=True)
		block_delivery(COMPANY_A)

	def test_reset_preserves_posted_invoice_archives_old_logins_and_retries_after_cache_loss(self):
		company, manifest = self.seed["company"], self.seed["manifest"]
		settings = frappe.get_doc("Company", company)
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": manifest["customers"]["cafe"],
				"posting_date": nowdate(),
				"due_date": add_days(nowdate(), 14),
				"currency": "USD",
				"debit_to": settings.default_receivable_account,
				"items": [
					{
						"item_code": manifest["service"],
						"qty": 1,
						"rate": 125,
						"income_account": settings.default_income_account,
						"cost_center": settings.cost_center,
					}
				],
			}
		).insert()
		invoice.submit()
		ledger = frappe.db.count("GL Entry", {"voucher_type": "Sales Invoice", "voucher_no": invoice.name})
		self.assertGreater(ledger, 0)
		production = frappe.db.count("Account", {"company": COMPANY_A})
		preview = demo.preview_reset(company)
		pid = preview["proposal"]["id"]
		result = demo.approve_reset(company, pid, "reset-once", PASSWORD)
		self.assertNotEqual(result["company"], company)
		self.assertEqual(result["generation"], 2)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 1)
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": invoice.name}), ledger)
		self.assertEqual(frappe.db.count("Account", {"company": COMPANY_A}), production)
		self.assertEqual(demo.get_demo(company)["status"], "Archived")
		self.assertEqual(demo.get_demo(company)["replacement"], result["company"])
		self.assertFalse(frappe.db.get_value("User", manifest["users"][1]["email"], "enabled"))
		FrappeCacheProposalStore().delete(company, pid)
		self.assertEqual(
			demo.approve_reset(company, pid, "reset-once", PASSWORD)["company"], result["company"]
		)


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveDemo)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Demo live acceptance checks failed")
	return {"passed": result.testsRun}
