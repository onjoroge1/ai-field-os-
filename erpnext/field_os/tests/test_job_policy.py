from unittest import TestCase

from erpnext.field_os.jobs.policy import failure_state, retry_seconds


class JobPolicy(TestCase):
	def test_unknown_provider_acceptance_never_auto_retries(self):
		for attempt in (1, 5, 20):
			self.assertEqual(failure_state(attempts=attempt, dispatched=True, replay_safe=False), "Uncertain")

	def test_known_safe_retries_are_bounded_and_back_off(self):
		self.assertEqual(failure_state(attempts=1, dispatched=False, replay_safe=False), "Retry")
		self.assertEqual(failure_state(attempts=5, dispatched=True, replay_safe=True), "Dead")
		self.assertEqual(
			failure_state(attempts=1, dispatched=False, replay_safe=True, permanent=True), "Dead"
		)
		self.assertEqual([retry_seconds(n) for n in (1, 2, 3, 100)], [30, 60, 120, 3600])
