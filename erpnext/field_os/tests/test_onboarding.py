from unittest import TestCase

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
