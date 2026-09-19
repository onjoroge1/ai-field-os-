from datetime import UTC, date, datetime
from unittest import TestCase

from erpnext.field_os.operations.models import (
	AttentionItem,
	AttentionSeverity,
	RecordLink,
	SearchResult,
)
from erpnext.field_os.operations.service import OperationsService
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class FakeOperationsRepository:
	def __init__(self):
		self.companies = []

	def list_attention(self, company, day, limit):
		self.companies.append(company)
		return [
			AttentionItem(
				"later", "today_jobs", AttentionSeverity.INFO, "Later", "", RecordLink("Job", "2", "Open")
			),
			AttentionItem(
				"urgent",
				"unassigned",
				AttentionSeverity.CRITICAL,
				"Urgent",
				"",
				RecordLink("Issue", "1", "Open"),
				datetime(2026, 9, 19, 12, tzinfo=UTC),
			),
		]

	def search(self, company, query, limit):
		self.companies.append(company)
		return [SearchResult("customer:C1", "customer", "Acme", query, RecordLink("Customer", "C1", "Open"))]


class TestOperationsService(TestCase):
	def setUp(self):
		self.context = TenantContext(
			"HVAC CO", "dispatcher@example.test", frozenset({FieldOSRole.DISPATCHER})
		)
		self.repository = FakeOperationsRepository()
		self.service = OperationsService(self.repository)

	def test_today_is_exception_first_and_tenant_scoped(self):
		snapshot = self.service.today(self.context, day=date(2026, 9, 19))
		self.assertEqual([item.id for item in snapshot.attention], ["urgent", "later"])
		self.assertEqual(snapshot.counts["critical"], 1)
		self.assertEqual(snapshot.counts["unassigned"], 1)
		self.assertEqual(self.repository.companies, ["HVAC CO"])

	def test_short_search_does_not_hit_repository(self):
		self.assertEqual(self.service.search(self.context, "x"), [])
		self.assertEqual(self.repository.companies, [])

	def test_search_uses_resolved_company(self):
		results = self.service.search(self.context, "acme")
		self.assertEqual(results[0].title, "Acme")
		self.assertEqual(self.repository.companies, ["HVAC CO"])
