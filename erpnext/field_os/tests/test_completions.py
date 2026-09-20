from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.completions.service import Completion, CompletionService, Line
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
		self.x = Completion(
			"W1",
			"CO",
			"C1",
			"Draft",
			(True,),
			"sig",
			("photo",),
			(Line("LAB", Decimal(1), Decimal(100), "Labor"),),
			"v1",
		)

	def get(self, c, i):
		return self.x

	def complete(self, c, i, u, v):
		self.x = Completion(
			"W1", c, "C1", "Completed", self.x.checks, self.x.signature, self.x.photos, self.x.lines, "v2"
		)
		return self.x

	def invoice(self, c, i, d, v):
		return "INV-1"


class TestCompletion(TestCase):
	def setUp(self):
		self.repo, self.store = Repo(), Store()
		self.tech = TenantContext("CO", "t", frozenset({FieldOSRole.TECHNICIAN}))
		self.bill = TenantContext("CO", "b", frozenset({FieldOSRole.BILLING}))
		self.service = CompletionService(self.repo, self.store)
		self.repo.invoice = Mock(wraps=self.repo.invoice)

	def preview(self):
		self.service.complete(self.tech, "W1", "v1")
		return self.service.preview_invoice(self.bill, "W1", date.today() + timedelta(days=30))[0]

	def test_invoice_rechecks_permission(self):
		p = self.preview()
		revoked = replace(self.bill, roles=frozenset({FieldOSRole.TECHNICIAN}))
		with self.assertRaises(CapabilityDenied):
			self.service.commit_invoice(revoked, p.id, "invoice", ActionEngine())
		self.repo.invoice.assert_not_called()

	def test_invoice_rejects_substituted_approval(self):
		p = self.preview()
		for change in (
			{"actor": "other"},
			{"company": "OTHER"},
			{"tool": "reset_demo"},
			{"risk": RiskClass.LOW},
		):
			with self.subTest(change=change):
				self.store.x[(self.bill.company, p.id)] = replace(p, **change)
				with self.assertRaises(ValueError):
					self.service.commit_invoice(self.bill, p.id, "invoice", ActionEngine())
		self.repo.invoice.assert_not_called()

	def test_invoice_rejects_changed_completion(self):
		p = self.preview()
		self.repo.x = replace(self.repo.x, version="changed")
		with self.assertRaises(ValueError):
			self.service.commit_invoice(self.bill, p.id, "invoice", ActionEngine())
		self.repo.invoice.assert_not_called()

	def test_invoice_retry_does_not_create_duplicate(self):
		p, engine = self.preview(), ActionEngine()
		first = self.service.commit_invoice(self.bill, p.id, "invoice", engine)
		self.repo.x = replace(self.repo.x, status="Invoiced", version="changed")
		self.assertEqual(first, self.service.commit_invoice(self.bill, p.id, "invoice", engine))
		self.repo.invoice.assert_called_once()

	def test_completion_rejects_missing_evidence_or_stale_version(self):
		original = self.repo.x
		for change in (
			{"checks": ()},
			{"checks": (False,)},
			{"signature": None},
			{"photos": ()},
			{"version": "old"},
		):
			with self.subTest(change=change):
				self.repo.x = replace(original, **change)
				with self.assertRaises(ValueError):
					self.service.complete(self.tech, "W1", "v1")

	def test_completion_rejects_invalid_billables(self):
		for quantity, rate in (("-1", "10"), ("1", "-1"), ("NaN", "10"), ("1", "Infinity")):
			with self.subTest(quantity=quantity, rate=rate):
				self.repo.x = replace(
					self.repo.x, lines=(Line("LAB", Decimal(quantity), Decimal(rate), "Labor"),)
				)
				with self.assertRaises(ValueError):
					self.service.complete(self.tech, "W1", "v1")

	def test_financial_approval(self):
		r, s = Repo(), Store()
		tech = TenantContext("CO", "t", frozenset({FieldOSRole.TECHNICIAN}))
		bill = TenantContext("CO", "b", frozenset({FieldOSRole.BILLING}))
		service = CompletionService(r, s)
		service.complete(tech, "W1", "v1")
		p, total = service.preview_invoice(bill, "W1", date.today() + timedelta(days=30))
		self.assertEqual(total, Decimal(100))
		self.assertEqual(
			service.commit_invoice(bill, p.id, "inv:w1", ActionEngine()).result["invoice_id"], "INV-1"
		)
