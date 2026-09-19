from datetime import date
from decimal import Decimal
from unittest import TestCase

from erpnext.field_os.adapter.types import (
	CustomerRecord,
	EquipmentRecord,
	InvoiceRecord,
	QuoteRecord,
	ServiceVisitRecord,
	SiteRecord,
)
from erpnext.field_os.customers.service import Customer360Service
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class FakeAdapter:
	def get_customer(self, customer_id):
		return CustomerRecord(customer_id, "Acme Dental", "ops@acme.test", "555-1000")

	def list_sites(self, customer_id):
		return [SiteRecord("SITE-1", customer_id, "Main office")]

	def list_equipment(self, customer_id):
		return [EquipmentRecord("UNIT-1", customer_id, "RTU-10", "SERIAL-1")]

	def list_service_visits(self, customer_id, limit=20):
		return [ServiceVisitRecord("VISIT-1", customer_id, date(2026, 9, 18), "Open", "Repair")]

	def list_quotes(self, customer_id, limit=20):
		return [QuoteRecord("QUOTE-1", customer_id, "Open", Decimal("1200"), "USD", date(2026, 9, 17))]

	def list_invoices(self, customer_id, limit=20):
		return [InvoiceRecord("INV-1", customer_id, "Overdue", Decimal("350"), "USD", date(2026, 9, 16))]


class FakeAccess:
	def __init__(self, allowed=True):
		self.allowed = allowed
		self.calls = []

	def can_access(self, company, customer_id):
		self.calls.append((company, customer_id))
		return self.allowed


class TestCustomer360(TestCase):
	def setUp(self):
		self.context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))

	def test_aggregates_open_work_money_and_timeline(self):
		access = FakeAccess()
		view = Customer360Service(FakeAdapter(), access).get(self.context, "CUST-1")
		self.assertEqual(view.customer.name, "Acme Dental")
		self.assertEqual(view.total_outstanding, Decimal("350"))
		self.assertEqual([item.kind for item in view.timeline], ["service", "quote", "invoice"])
		self.assertEqual(access.calls, [("HVAC CO", "CUST-1")])

	def test_rejects_customer_not_proven_in_tenant(self):
		with self.assertRaises(PermissionError):
			Customer360Service(FakeAdapter(), FakeAccess(False)).get(self.context, "CUST-OTHER")
