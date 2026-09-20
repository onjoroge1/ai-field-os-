from datetime import date
from unittest import TestCase

from erpnext.field_os.agreements.service import Agreement, AgreementService, add_months
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class Repo:
	def list(self, c):
		return [Agreement("A1", c, "C1", "S1", "Active", date(2026, 1, 31), date(2027, 1, 31), 3, 45)]

	def completed(self, c, i):
		return [date(2026, 4, 30)]


class TestAgreements(TestCase):
	def test_due_overdue_and_month_math(self):
		ctx = TenantContext("CO", "m", frozenset({FieldOSRole.MANAGER}))
		d = AgreementService(Repo()).dashboard(ctx, date(2026, 8, 1))
		self.assertEqual(d["overdue"][0].due_on, date(2026, 7, 30))
		self.assertEqual(add_months(date(2025, 1, 31), 1), date(2025, 2, 28))
