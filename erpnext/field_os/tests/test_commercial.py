import unittest
from datetime import date

from erpnext.field_os.commercial.policy import PLANS, EntitlementDenied, period, require_access, require_quota


class CommercialPolicy(unittest.TestCase):
	def test_trial_and_grace_boundaries(self):
		for status, key in (("trialing", "trial_end"), ("past_due", "grace_end")):
			doc = {"plan": "trial", "status": status, key: "2030-01-31"}
			self.assertEqual(require_access(doc, today=date(2030, 1, 31)), PLANS["trial"])
			with self.assertRaises(EntitlementDenied):
				require_access(doc, today=date(2030, 2, 1))
			doc[key] = None
			with self.assertRaises(EntitlementDenied):
				require_access(doc, today=date(2030, 1, 1))

	def test_status_and_features_fail_closed(self):
		for status in ("suspended", "canceled", "unknown"):
			with self.assertRaises(EntitlementDenied):
				require_access({"plan": "pro", "status": status}, today=date.today())
		with self.assertRaises(EntitlementDenied):
			require_access(
				{"plan": "pro", "status": "active", "disabled_features": ["sms"]}, "sms", today=date.today()
			)

	def test_quotas_are_exact_and_cannot_be_refunded_by_negative_usage(self):
		require_quota(PLANS["trial"], "sms", 99, 1)
		with self.assertRaises(EntitlementDenied):
			require_quota(PLANS["trial"], "sms", 100, 1)
		for amount in (-1, 0, True, 1.2):
			with self.assertRaises(ValueError):
				require_quota(PLANS["trial"], "sms", 0, amount)
		self.assertEqual(period(date(2030, 12, 31)), "2030-12")
		self.assertEqual(period(date(2031, 1, 1)), "2031-01")
