from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.demo.service import Demo, DemoService
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class Store:
	def __init__(self):
		self.x = {}

	def save(self, p):
		self.x[(p.company, p.id)] = p

	def load(self, c, i):
		return self.x[(c, i)]


class Repo:
	def __init__(self):
		self.d = None

	def get(self, c):
		return self.d

	def seed(self, c):
		self.d = Demo(c, "Ready", "v1", (("Customer", "C1"), ("Field OS HVAC Equipment", "E1")))
		return self.d

	def reset(self, c):
		return self.seed(c)


class TestDemo(TestCase):
	def test_seed_scenarios_and_reset(self):
		r, s = Repo(), Store()
		ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		d = DemoService(r, s)
		d.seed(ctx)
		self.assertEqual(len(d.scenarios(ctx)), 3)
		p = d.preview_reset(ctx)
		self.assertEqual(d.reset(ctx, p.id, "reset:v1", ActionEngine()).result.status, "Ready")
