from unittest import TestCase

from erpnext.field_os.observability.policy import cost_microusd, latency_bucket, operation, percentile


class ObservabilityPolicy(TestCase):
	def test_private_or_unrecognized_labels_collapse_to_bounded_group(self):
		self.assertEqual(operation("erpnext.field_os.api.email.approve_send"), "email")
		self.assertEqual(operation("erpnext.field_os.api.secret-user@example.test.run"), "other")
		self.assertEqual(operation(None), "other")

	def test_percentile_and_overflow_are_not_reported_as_zero(self):
		self.assertEqual(latency_bucket(250), "250")
		self.assertEqual(latency_bucket(70000), "overflow")
		self.assertEqual(percentile({"50": 94, "5000": 6}), 5000)
		self.assertIsNone(percentile({}))

	def test_missing_cost_is_unknown_and_valid_tokens_are_priced(self):
		self.assertEqual(cost_microusd(1000, 100, {"input": 2, "output": 8}), 2800)
		self.assertIsNone(cost_microusd(None, 100, {"input": 2, "output": 8}))
		self.assertIsNone(cost_microusd(1, 1, {"input": float("nan"), "output": 1}))
