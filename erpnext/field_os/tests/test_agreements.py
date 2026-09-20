from dataclasses import replace
from datetime import date
from unittest import TestCase
from unittest.mock import Mock

from erpnext.field_os.agreements.service import Agreement, AgreementService, add_months
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class Repo:
	def list(self, c):
		return [Agreement("A1", c, "C1", "S1", "Active", date(2026, 1, 31), date(2027, 1, 31), 3, 45)]

	def completed(self, c, i):
		return [date(2026, 4, 30)]


class TestAgreements(TestCase):
	def test_invalid_cadence_is_rejected(self):
		agreement = Repo().list("CO")[0]
		for interval in (0, -1, 61, 1.5, True):
			with self.subTest(interval=interval), self.assertRaises(ValueError):
				replace(agreement, interval_months=interval)

	def test_expired_agreement_is_not_an_upcoming_renewal(self):
		ctx = TenantContext("CO", "m", frozenset({FieldOSRole.MANAGER}))
		self.assertEqual(AgreementService(Repo()).dashboard(ctx, date(2027, 2, 1))["renewals"], ())

	def test_future_completion_does_not_hide_overdue_visit(self):
		repo = Repo()
		repo.completed = Mock(return_value=[date(2026, 4, 30), date(2026, 12, 1)])
		ctx = TenantContext("CO", "m", frozenset({FieldOSRole.MANAGER}))
		self.assertEqual(
			AgreementService(repo).dashboard(ctx, date(2026, 8, 1))["overdue"][0].due_on, date(2026, 7, 30)
		)

	def test_due_overdue_and_month_math(self):
		ctx = TenantContext("CO", "m", frozenset({FieldOSRole.MANAGER}))
		d = AgreementService(Repo()).dashboard(ctx, date(2026, 8, 1))
		self.assertEqual(d["overdue"][0].due_on, date(2026, 7, 30))
		self.assertEqual(add_months(date(2025, 1, 31), 1), date(2025, 2, 28))
