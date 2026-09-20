from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.migrations.service import Batch, MigrationService
from erpnext.field_os.security.authorization import CapabilityDenied
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
	def setUp(self):
		self.repo, self.store = Repo(), Store()
		self.ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		self.service = MigrationService(self.repo, self.store)

	def prepare_rollback(self):
		batch = self.service.validate(
			self.ctx, "customers", "customer_id,customer_name,email,phone\nC1,Alex,,\n"
		)
		self.service.apply(self.ctx, batch.id)
		self.repo.rollback = Mock(wraps=self.repo.rollback)
		return self.service.preview_rollback(self.ctx, batch.id)

	def test_csv_duplicate_columns_are_rejected(self):
		with self.assertRaisesRegex(ValueError, "columns"):
			self.service.validate(
				self.ctx, "customers", "customer_id,customer_name,customer_name\nC1,Alex,Sam\n"
			)

	def test_csv_extra_values_produce_row_error(self):
		batch = self.service.validate(self.ctx, "customers", "customer_id,customer_name\nC1,Alex,extra\n")
		self.assertTrue(batch.rows[0].errors)
		with self.assertRaises(ValueError):
			self.service.apply(self.ctx, batch.id)

	def test_csv_duplicate_identifiers_cannot_apply(self):
		batch = self.service.validate(self.ctx, "customers", "customer_id,customer_name\nC1,Alex\nC1,Sam\n")
		self.assertIn("duplicate identifier: C1", batch.rows[1].errors)
		with self.assertRaises(ValueError):
			self.service.apply(self.ctx, batch.id)

	def test_apply_does_not_trust_status_over_row_errors(self):
		batch = self.service.validate(self.ctx, "customers", "customer_id,customer_name\nC1,\n")
		self.repo.b[batch.id] = replace(batch, status="Validated")
		with self.assertRaises(ValueError):
			self.service.apply(self.ctx, batch.id)

	def test_apply_retry_returns_existing_batch(self):
		batch = self.service.validate(self.ctx, "customers", "customer_id,customer_name\nC1,Alex\n")
		self.repo.apply = Mock(wraps=self.repo.apply)
		first = self.service.apply(self.ctx, batch.id)
		self.assertEqual(first, self.service.apply(self.ctx, batch.id))
		self.repo.apply.assert_called_once()

	def test_rollback_rechecks_admin_permission(self):
		p = self.prepare_rollback()
		revoked = replace(self.ctx, roles=frozenset({FieldOSRole.MANAGER}))
		with self.assertRaises(CapabilityDenied):
			self.service.rollback(revoked, p.id, "rollback", ActionEngine())
		self.repo.rollback.assert_not_called()

	def test_rollback_rejects_substituted_approval(self):
		p = self.prepare_rollback()
		for change in (
			{"actor": "other"},
			{"company": "OTHER"},
			{"tool": "reset_demo"},
			{"risk": RiskClass.LOW},
		):
			with self.subTest(change=change):
				self.store.x[(self.ctx.company, p.id)] = replace(p, **change)
				with self.assertRaises(ValueError):
					self.service.rollback(self.ctx, p.id, "rollback", ActionEngine())
		self.repo.rollback.assert_not_called()

	def test_rollback_rejects_changed_manifest(self):
		p = self.prepare_rollback()
		self.repo.b["M1"] = replace(self.repo.b["M1"], created=(("Customer", "C2"),))
		with self.assertRaises(ValueError):
			self.service.rollback(self.ctx, p.id, "rollback", ActionEngine())
		self.repo.rollback.assert_not_called()

	def test_rollback_retry_returns_receipt(self):
		p, engine = self.prepare_rollback(), ActionEngine()
		first = self.service.rollback(self.ctx, p.id, "rollback", engine)
		self.assertEqual(first, self.service.rollback(self.ctx, p.id, "rollback", engine))
		self.repo.rollback.assert_called_once()

	def test_dry_run_apply_and_rollback(self):
		r, s = Repo(), Store()
		ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		m = MigrationService(r, s)
		b = m.validate(ctx, "customers", "customer_id,customer_name,email,phone\nC1,Alex,,\n")
		self.assertEqual(m.apply(ctx, b.id).status, "Applied")
		p = m.preview_rollback(ctx, b.id)
		self.assertEqual(m.rollback(ctx, p.id, "rb:m1", ActionEngine()).result.status, "Rolled Back")
