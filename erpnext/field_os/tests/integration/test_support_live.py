import unittest
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from erpnext.field_os.api import support
from erpnext.field_os.commercial import native
from erpnext.field_os.support import service
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER, prepare_onboarding

STAFF = "fieldos-support@example.invalid"


class LiveSupport(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare_onboarding()
		service.ensure_role()
		if not frappe.db.exists("User", STAFF):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": STAFF,
					"first_name": "FieldOS Support",
					"send_welcome_email": 0,
					"roles": [{"role": service.SUPPORT_ROLE}],
				}
			).insert()

	def setUp(self):
		frappe.db.savepoint("support_test")
		frappe.set_user(OWNER)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="support_test")
		frappe.clear_cache()

	def grant(self):
		return support.grant(COMPANY_A, STAFF, "Investigate failed mailbox sync", 30)[0]["name"]

	def test_scoped_grant_allows_diagnostics_without_impersonation(self):
		name = self.grant()
		frappe.set_user(STAFF)
		data = support.inspect(COMPANY_A, name, "Check mailbox availability")
		self.assertEqual(data["company"], COMPANY_A)
		self.assertEqual(frappe.session.user, STAFF)
		with self.assertRaises(frappe.PermissionError):
			support.inspect(COMPANY_B, name, "Check another mailbox")
		with self.assertRaises(frappe.PermissionError):
			support.set_flags(COMPANY_A, [], data["version"], "Enable a customer feature")
		with self.assertRaises(frappe.PermissionError):
			service.resolve_tenant_context(COMPANY_A)

	def test_revocation_and_expiry_are_immediate(self):
		name = self.grant()
		support.revoke(COMPANY_A, name)
		frappe.set_user(STAFF)
		with self.assertRaises(frappe.PermissionError):
			support.inspect(COMPANY_A, name, "Check revoked grant")
		frappe.set_user(OWNER)
		name = self.grant()
		frappe.db.set_value(service.GRANT, name, "expires_at", now_datetime() - timedelta(seconds=1))
		frappe.set_user(STAFF)
		with self.assertRaises(frappe.PermissionError):
			support.inspect(COMPANY_A, name, "Check expired grant")

	def test_audit_is_permanent_and_feature_changes_are_version_bound(self):
		self.grant()
		row = frappe.get_doc(service.AUDIT, {"company": COMPANY_A, "action": "support.granted"})
		row.action = "rewritten"
		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(service.AUDIT, row.name, ignore_permissions=True)
		frappe.set_user("Administrator")
		version = str(native.subscription(COMPANY_A).modified)
		result = support.set_flags(COMPANY_A, ["sms"], version, "Pause this company SMS feature")
		self.assertEqual(result["subscription"]["disabled_features"], ["sms"])
		with self.assertRaises(frappe.TimestampMismatchError):
			support.set_flags(COMPANY_A, [], version, "Stale feature-change request")

	def test_owner_must_grant_valid_staff_and_bounded_duration(self):
		with self.assertRaises(frappe.ValidationError):
			support.grant(COMPANY_A, OWNER, "Not a support account", 30)
		with self.assertRaises(frappe.ValidationError):
			support.grant(COMPANY_A, STAFF, "Too much support time", 120)
		with self.assertRaises(frappe.PermissionError):
			support.grant(COMPANY_B, STAFF, "Another company support", 30)


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveSupport)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Support acceptance failed")
	return {"passed": result.testsRun}
