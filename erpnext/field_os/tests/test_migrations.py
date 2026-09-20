from dataclasses import replace
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.migrations.service import Batch, MigrationService
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
		self.b = {}

	def create(self, c, k, r, u):
		x = Batch("M1", c, k, "Failed Validation" if any(i.errors for i in r) else "Validated", r)
		self.b[x.id] = x
		return x

	def get(self, c, i):
		return self.b[i]

	def apply(self, c, i):
		self.b[i] = replace(self.b[i], status="Applied", created=(("Customer", "C1"),))
		return self.b[i]

	def rollback(self, c, i):
		self.b[i] = replace(self.b[i], status="Rolled Back")
		return self.b[i]


class TestMigration(TestCase):
	def test_dry_run_apply_and_rollback(self):
		r, s = Repo(), Store()
		ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		m = MigrationService(r, s)
		b = m.validate(ctx, "customers", "customer_id,customer_name,email,phone\nC1,Alex,,\n")
		self.assertEqual(m.apply(ctx, b.id).status, "Applied")
		p = m.preview_rollback(ctx, b.id)
		self.assertEqual(m.rollback(ctx, p.id, "rb:m1", ActionEngine()).result.status, "Rolled Back")
