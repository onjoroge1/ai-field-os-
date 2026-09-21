"""Native quota, immutable ledger, access and seat admission acceptance."""

import unittest
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import getdate

from erpnext.field_os.api import commercial, onboarding
from erpnext.field_os.commercial import native
from erpnext.field_os.commercial.policy import EntitlementDenied, period
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B, MANAGER, OTHER
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER, prepare_onboarding


class LiveCommercial(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare_onboarding()
		native.migrate_subscriptions()

	def setUp(self):
		frappe.db.savepoint("commercial_test")
		frappe.set_user(OWNER)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="commercial_test")
		frappe.clear_cache()

	def test_durable_deduplication_and_tenant_scoped_usage(self):
		first = native.consume(COMPANY_A, "sms", "provider-message", amount=2)
		self.assertEqual(native.consume(COMPANY_A, "sms", "provider-message", amount=2), first)
		self.assertEqual(native.totals(COMPANY_A, period(getdate()))["sms"], 2)
		self.assertNotEqual(native.consume(COMPANY_B, "sms", "provider-message", amount=2), first)
		with self.assertRaises(ValueError):
			native.consume(COMPANY_A, "sms", "provider-message", amount=1)
		doc = frappe.get_doc(native.USAGE, first)
		doc.quantity = 0
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(native.USAGE, first, ignore_permissions=True)

	def test_limits_block_before_spending_and_next_month_is_separate(self):
		native.consume(COMPANY_A, "sms", "all", amount=100)
		with self.assertRaises(EntitlementDenied):
			native.consume(COMPANY_A, "sms", "too-many")
		self.assertEqual(native.totals(COMPANY_A, period(getdate()))["sms"], 100)
		self.assertFalse(native.totals(COMPANY_A, "2099-01"))

	def test_owner_view_and_native_record_permissions(self):
		self.assertEqual(commercial.get_plan(COMPANY_A)["plan"], "trial")
		with self.assertRaises(frappe.PermissionError):
			commercial.get_plan(COMPANY_B)
		with self.assertRaises(frappe.PermissionError):
			native.subscription(COMPANY_A).save()
		frappe.set_user(OTHER)
		self.assertFalse(
			frappe.has_permission(native.SUBSCRIPTION, "read", doc=native.subscription(COMPANY_A))
		)
		frappe.set_user(MANAGER)
		with self.assertRaises(PermissionError):
			commercial.get_plan(COMPANY_A)

	def test_expired_trial_blocks_changes_but_keeps_read_and_plan_access(self):
		doc = native.subscription(COMPANY_A)
		doc.trial_end = getdate() - timedelta(days=1)
		doc.save(ignore_permissions=True)
		self.assertEqual(commercial.get_plan(COMPANY_A)["status"], "trialing")
		onboarding.get_setup(COMPANY_A)
		with self.assertRaises(EntitlementDenied):
			onboarding.save_step(COMPANY_A, "notifications", {}, "new")

	def test_membership_and_feature_flags_are_enforced(self):
		with patch.object(native, "members", return_value={f"seat-{i}" for i in range(10)}):
			with self.assertRaises(frappe.ValidationError):
				native.seat(COMPANY_A, "eleventh")
		doc = native.subscription(COMPANY_A)
		doc.disabled_features_json = '["sms"]'
		doc.save(ignore_permissions=True)
		with self.assertRaises(EntitlementDenied):
			native.consume(COMPANY_A, "sms", "disabled")


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveCommercial)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Commercial acceptance failed")
	return {"passed": result.testsRun}
