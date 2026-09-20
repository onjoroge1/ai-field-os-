from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.demo.service import Demo, DemoService
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
		self.d = None

	def get(self, c):
		return self.d

	def seed(self, c):
		self.d = Demo(c, "Ready", "v1", (("Customer", "C1"), ("Field OS HVAC Equipment", "E1")))
		return self.d

	def reset(self, c):
		return self.seed(c)


class TestDemo(TestCase):
	def setUp(self):
		self.repo, self.store = Repo(), Store()
		self.ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		self.service = DemoService(self.repo, self.store)
		self.service.seed(self.ctx)
		self.proposal = self.service.preview_reset(self.ctx)
		self.repo.reset = Mock(wraps=self.repo.reset)

	def test_seed_reuses_existing_manifest(self):
		self.repo.seed = Mock(wraps=self.repo.seed)
		self.assertEqual(self.service.seed(self.ctx), self.repo.d)
		self.repo.seed.assert_not_called()

	def test_reset_rechecks_admin_permission(self):
		revoked = replace(self.ctx, roles=frozenset({FieldOSRole.MANAGER}))
		with self.assertRaises(CapabilityDenied):
			self.service.reset(revoked, self.proposal.id, "reset", ActionEngine())
		self.repo.reset.assert_not_called()

	def test_reset_rejects_substituted_approval(self):
		for change in (
			{"actor": "other"},
			{"company": "OTHER"},
			{"tool": "rollback_migration"},
			{"risk": RiskClass.LOW},
		):
			with self.subTest(change=change):
				self.store.x[(self.ctx.company, self.proposal.id)] = replace(self.proposal, **change)
				with self.assertRaises(ValueError):
					self.service.reset(self.ctx, self.proposal.id, "reset", ActionEngine())
		self.repo.reset.assert_not_called()

	def test_reset_rejects_changed_manifest_even_at_same_size(self):
		self.repo.d = replace(self.repo.d, records=(("Customer", "OTHER"), ("Field OS HVAC Equipment", "E1")))
		with self.assertRaises(ValueError):
			self.service.reset(self.ctx, self.proposal.id, "reset", ActionEngine())
		self.repo.reset.assert_not_called()

	def test_reset_rejects_changed_seed_version(self):
		self.repo.d = replace(self.repo.d, seed_version="v2")
		with self.assertRaises(ValueError):
			self.service.reset(self.ctx, self.proposal.id, "reset", ActionEngine())
		self.repo.reset.assert_not_called()

	def test_reset_retry_returns_receipt_after_reseed(self):
		engine = ActionEngine()
		first = self.service.reset(self.ctx, self.proposal.id, "reset", engine)
		self.repo.d = replace(self.repo.d, seed_version="v2")
		self.assertEqual(first, self.service.reset(self.ctx, self.proposal.id, "reset", engine))
		self.repo.reset.assert_called_once()

	def test_seed_scenarios_and_reset(self):
		r, s = Repo(), Store()
		ctx = TenantContext("CO", "o", frozenset({FieldOSRole.OWNER}))
		d = DemoService(r, s)
		d.seed(ctx)
		self.assertEqual(len(d.scenarios(ctx)), 3)
		p = d.preview_reset(ctx)
		self.assertEqual(d.reset(ctx, p.id, "reset:v1", ActionEngine()).result.status, "Ready")
