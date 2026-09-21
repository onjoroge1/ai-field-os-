import unittest
from datetime import UTC, datetime

from erpnext.field_os.commercial.billing_policy import hosted_url, subscription_values


class BillingPolicy(unittest.TestCase):
	def remote(self, status="active"):
		return {
			"id": "sub_test",
			"status": status,
			"items": {
				"data": [{"quantity": 1, "price": {"id": "price_std"}, "current_period_end": 2000000000}]
			},
		}

	def test_active_and_suspended_provider_states(self):
		for status in ("active", "trialing", "past_due", "canceled", "unpaid", "incomplete", "paused"):
			value = subscription_values(self.remote(status), {"standard": "price_std"}, {}, datetime.now(UTC))
			self.assertEqual(
				value["status"],
				status if status in {"active", "trialing", "past_due", "canceled"} else "suspended",
			)

	def test_unknown_or_multiple_prices_never_grant_access(self):
		for items in (
			[],
			[{"quantity": 2, "price": {"id": "price_std"}}],
			[{"quantity": 1, "price": {"id": "foreign"}}],
		):
			remote = self.remote()
			remote["items"]["data"] = items
			with self.assertRaises(ValueError):
				subscription_values(remote, {"standard": "price_std"}, {}, datetime.now(UTC))

	def test_duplicate_failures_do_not_extend_grace(self):
		first = subscription_values(
			self.remote("past_due"), {"standard": "price_std"}, {}, datetime(2030, 1, 1, tzinfo=UTC)
		)
		second = subscription_values(
			self.remote("past_due"), {"standard": "price_std"}, first, datetime(2030, 1, 6, tzinfo=UTC)
		)
		self.assertEqual(first["grace_end"], second["grace_end"])
		self.assertEqual(second["grace_end"], "2030-01-08")

	def test_redirect_hosts_are_exact(self):
		self.assertEqual(
			hosted_url("https://checkout.stripe.com/test", "checkout.stripe.com"),
			"https://checkout.stripe.com/test",
		)
		for url in (
			"https://checkout.stripe.com.evil.invalid/a",
			"javascript:alert(1)",
			"https://user@checkout.stripe.com/a",
			"http://checkout.stripe.com/a",
		):
			with self.assertRaises(ValueError):
				hosted_url(url, "checkout.stripe.com")
