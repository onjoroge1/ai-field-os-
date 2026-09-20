from unittest import TestCase
from unittest.mock import Mock

from erpnext.field_os.onboarding.service import OnboardingService, State
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class Repo:
	def __init__(self):
		self.done = []
		self.status = "Not Started"

	def state(self, c):
		return State(c, self.status, tuple(self.done))

	def save(self, c, s, p):
		self.done.append(s)
		self.status = "In Progress"
		return self.state(c)

	def checks(self, c):
		return {"erpnext": True}

	def complete(self, c):
		self.status = "Completed"
		return self.state(c)


class TestOnboarding(TestCase):
	def test_completion_requires_actual_integration_results(self):
		ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		for checks in ({}, {"erpnext": False}, {"erpnext": "passed"}):
			with self.subTest(checks=checks):
				repo = Repo()
				repo.done = list(OnboardingService.steps)
				repo.checks = Mock(return_value=checks)
				repo.complete = Mock()
				with self.assertRaises(ValueError):
					OnboardingService(repo).complete(ctx)
				repo.complete.assert_not_called()

	def test_invalid_role_payload_does_not_save(self):
		ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		repo = Repo()
		repo.save = Mock()
		for roles in (None, [], "Field OS Owner", ["System Manager"], [{}]):
			with self.subTest(roles=roles), self.assertRaises(ValueError):
				OnboardingService(repo).configure(ctx, "users", [{"roles": roles}])
		repo.save.assert_not_called()

	def test_required_steps(self):
		r = Repo()
		s = OnboardingService(r)
		c = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		with self.assertRaises(ValueError):
			s.complete(c)
		for step in s.steps:
			s.configure(
				c, step, [{"roles": [FieldOSRole.OWNER.value]}] if step == "users" else [{"value": 1}]
			)
		self.assertEqual(s.complete(c).status, "Completed")
