from dataclasses import replace
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.estimates.models import Estimate, EstimateLine
from erpnext.field_os.estimates.service import EstimateService
from erpnext.field_os.security.authorization import CapabilityDenied
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class Store:
	def __init__(self):
		self.x = {}

	def save(self, p):
		self.x[(p.company, p.id)] = p

	def load(self, c, i):
		return self.x.get((c, i))


class Repo:
	def __init__(self):
		self.e = Estimate(
			"Q1",
			"CO",
			"C1",
			"Draft",
			"USD",
			None,
			(EstimateLine("P1", "Part", Decimal(2), Decimal(10)),),
			"v1",
		)

	def get(self, c, i):
		if c != self.e.company:
			raise ValueError("tenant")
		return self.e

	def stock(self, c, i, w):
		return Decimal(1)

	def set_status(self, c, i, s, v):
		self.e = Estimate("Q1", c, "C1", s, "USD", None, self.e.lines, "v2")
		return self.e


class TestEstimates(TestCase):
	def setUp(self):
		self.repo, self.store = Repo(), Store()
		self.ctx = TenantContext("CO", "m", frozenset({FieldOSRole.MANAGER}))
		self.service = EstimateService(self.repo, self.store)
		self.proposal, _ = self.service.preview_send(self.ctx, "Q1")
		self.repo.set_status = Mock(wraps=self.repo.set_status)

	def test_commit_rechecks_current_permission(self):
		revoked = replace(self.ctx, roles=frozenset({FieldOSRole.TECHNICIAN}))
		with self.assertRaises(CapabilityDenied):
			self.service.commit_send(revoked, self.proposal.id, "send", ActionEngine())
		self.repo.set_status.assert_not_called()

	def test_commit_rejects_substituted_approval(self):
		for change in ({"actor": "other"}, {"company": "OTHER"}, {"tool": "other"}, {"risk": RiskClass.LOW}):
			with self.subTest(change=change):
				self.store.x[(self.ctx.company, self.proposal.id)] = replace(self.proposal, **change)
				with self.assertRaises(ValueError):
					self.service.commit_send(self.ctx, self.proposal.id, "send", ActionEngine())
		self.repo.set_status.assert_not_called()

	def test_commit_rejects_changed_estimate(self):
		self.repo.e = replace(self.repo.e, version="changed")
		with self.assertRaises(ValueError):
			self.service.commit_send(self.ctx, self.proposal.id, "send", ActionEngine())
		self.repo.set_status.assert_not_called()

	def test_retry_returns_receipt_without_sending_again(self):
		engine = ActionEngine()
		first = self.service.commit_send(self.ctx, self.proposal.id, "send", engine)
		self.assertEqual(first, self.service.commit_send(self.ctx, self.proposal.id, "send", engine))
		self.repo.set_status.assert_called_once()

	def test_approval_and_parts_shortage(self):
		r, s = Repo(), Store()
		ctx = TenantContext("CO", "m", frozenset({FieldOSRole.MANAGER}))
		service = EstimateService(r, s)
		p, short = service.preview_send(ctx, "Q1")
		self.assertEqual(short[0].item_code, "P1")
		service.commit_send(ctx, p.id, "send:q1", ActionEngine())
		self.assertEqual(r.e.status, "Sent")
		service.customer_decision(ctx, "Q1", "Approved")
		self.assertEqual(r.e.status, "Approved")
