import unittest
from unittest.mock import patch
from uuid import uuid4

import frappe

from erpnext.field_os.observability import service
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER, prepare_onboarding


class LiveObservability(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		prepare_onboarding()

	def test_metrics_survive_transaction_rollback_and_logs_exclude_payload(self):
		company = "telemetry-" + uuid4().hex
		key = service.key(company, 10000)
		try:
			frappe.db.savepoint("telemetry_test")
			with patch.object(service.time, "time", return_value=600000), patch.object(
				frappe, "logger"
			) as logger:
				service.record("email", company=company, duration_ms=300, failed=True)
				frappe.db.rollback(save_point="telemetry_test")
				metric = service.aggregate(company)
				self.assertEqual((metric["spans"], metric["errors"], metric["p95_ms"]), (1, 1, 500))
				log = logger.return_value.info.call_args.args[0]
				self.assertNotIn("password", log)
				self.assertIn('"trace_id"', log)
		finally:
			frappe.cache.delete(key)

	def test_dashboard_cannot_read_another_tenant(self):
		frappe.set_user(OWNER)
		try:
			self.assertEqual(service.dashboard(COMPANY_A)["window_minutes"], 60)
			with self.assertRaises(frappe.PermissionError):
				service.dashboard(COMPANY_B)
		finally:
			frappe.set_user("Administrator")


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveObservability)
	)
	if not result.wasSuccessful():
		raise AssertionError("Observability acceptance failed")
	return {"passed": result.testsRun}
