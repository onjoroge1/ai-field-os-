"""Tenant-safe customer 360 aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from erpnext.field_os.adapter.base import FieldOperationsAdapter
from erpnext.field_os.adapter.types import (
	CustomerRecord,
	EquipmentRecord,
	InvoiceRecord,
	QuoteRecord,
	ServiceVisitRecord,
	SiteRecord,
)
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


class CustomerAccessPolicy(Protocol):
	def can_access(self, company: str, customer_id: str) -> bool:
		...


@dataclass(frozen=True, slots=True)
class TimelineEvent:
	id: str
	kind: str
	title: str
	summary: str
	occurred_on: date | datetime | None
	doctype: str
	record_id: str


@dataclass(frozen=True, slots=True)
class Customer360:
	customer: CustomerRecord
	sites: tuple[SiteRecord, ...]
	equipment: tuple[EquipmentRecord, ...]
	open_work: tuple[ServiceVisitRecord, ...]
	open_quotes: tuple[QuoteRecord, ...]
	open_invoices: tuple[InvoiceRecord, ...]
	timeline: tuple[TimelineEvent, ...]
	total_outstanding: Decimal


class Customer360Service:
	def __init__(self, adapter: FieldOperationsAdapter, access: CustomerAccessPolicy) -> None:
		self.adapter = adapter
		self.access = access

	def get(self, context: TenantContext, customer_id: str) -> Customer360:
		authorize(context, "read")
		if not self.access.can_access(context.company, customer_id):
			raise PermissionError("Customer is not available in this tenant")

		customer = self.adapter.get_customer(customer_id)
		sites = tuple(self.adapter.list_sites(customer_id))
		equipment = tuple(self.adapter.list_equipment(customer_id))
		visits = tuple(self.adapter.list_service_visits(customer_id, limit=100))
		quotes = tuple(self.adapter.list_quotes(customer_id, limit=100))
		invoices = tuple(self.adapter.list_invoices(customer_id, limit=100))
		open_work = tuple(item for item in visits if item.status.lower() not in {"completed", "cancelled"})
		open_quotes = tuple(
			item for item in quotes if item.status.lower() not in {"ordered", "lost", "expired"}
		)
		open_invoices = tuple(item for item in invoices if item.outstanding_amount > 0)
		timeline = self._timeline(visits, quotes, invoices)
		return Customer360(
			customer,
			sites,
			equipment,
			open_work,
			open_quotes,
			open_invoices,
			timeline,
			sum((item.outstanding_amount for item in open_invoices), Decimal(0)),
		)

	@staticmethod
	def _timeline(
		visits: tuple[ServiceVisitRecord, ...],
		quotes: tuple[QuoteRecord, ...],
		invoices: tuple[InvoiceRecord, ...],
	) -> tuple[TimelineEvent, ...]:
		events = [
			TimelineEvent(
				f"visit:{item.id}",
				"service",
				f"Service visit · {item.status}",
				item.maintenance_type or "Field service",
				item.visit_date,
				"Maintenance Visit",
				item.id,
			)
			for item in visits
		]
		events.extend(
			TimelineEvent(
				f"quote:{item.id}",
				"quote",
				f"Quote · {item.status}",
				f"{item.currency} {item.total}",
				item.transaction_date,
				"Quotation",
				item.id,
			)
			for item in quotes
		)
		events.extend(
			TimelineEvent(
				f"invoice:{item.id}",
				"invoice",
				f"Invoice · {item.status}",
				f"{item.currency} {item.outstanding_amount} outstanding",
				item.posting_date,
				"Sales Invoice",
				item.id,
			)
			for item in invoices
		)
		events.sort(
			key=lambda item: (item.occurred_on is not None, item.occurred_on or date.min), reverse=True
		)
		return tuple(events)
