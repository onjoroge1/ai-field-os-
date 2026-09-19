"""Port implemented by any operational system behind Field OS."""

from __future__ import annotations

from typing import Protocol

from erpnext.field_os.adapter.types import (
	CustomerRecord,
	EquipmentRecord,
	InvoiceRecord,
	QuoteRecord,
	ServiceVisitRecord,
	SiteRecord,
)


class FieldOperationsAdapter(Protocol):
	def get_customer(self, customer_id: str) -> CustomerRecord:
		...

	def find_customers(self, query: str, limit: int = 20) -> list[CustomerRecord]:
		...

	def list_sites(self, customer_id: str) -> list[SiteRecord]:
		...

	def list_equipment(self, customer_id: str) -> list[EquipmentRecord]:
		...

	def list_service_visits(self, customer_id: str, limit: int = 20) -> list[ServiceVisitRecord]:
		...

	def list_quotes(self, customer_id: str, limit: int = 20) -> list[QuoteRecord]:
		...

	def list_invoices(self, customer_id: str, limit: int = 20) -> list[InvoiceRecord]:
		...
