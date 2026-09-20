from datetime import date, timedelta
from decimal import Decimal
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.completions.service import Completion, CompletionService, Line
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
