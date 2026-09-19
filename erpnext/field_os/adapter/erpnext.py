"""ERPNext implementation of the Field OS adapter.

Only this module should translate ERPNext/Frappe records into the normalized
records consumed by Field OS.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import frappe

from erpnext.field_os.adapter.errors import AdapterUnavailable, RecordNotFound
from erpnext.field_os.adapter.types import (
	CustomerRecord,
	EquipmentRecord,
	InvoiceRecord,
	QuoteRecord,
	ServiceVisitRecord,
	SiteRecord,
)


def _decimal(value: Any) -> Decimal:
	return Decimal(str(value or 0))


class ERPNextAdapter:
	def _get_all(self, doctype: str, **kwargs):
		try:
			return frappe.get_all(doctype, **kwargs)
		except Exception as exc:
			raise AdapterUnavailable(f"ERPNext read failed for {doctype}") from exc

	def get_customer(self, customer_id: str) -> CustomerRecord:
		rows = self._get_all(
			"Customer",
			filters={"name": customer_id},
			fields=["name", "customer_name", "email_id", "mobile_no"],
			limit=1,
		)
		if not rows:
			raise RecordNotFound(f"Customer not found: {customer_id}")
		return self._customer(rows[0])

	def find_customers(self, query: str, limit: int = 20) -> list[CustomerRecord]:
		limit = max(1, min(limit, 100))
		rows = self._get_all(
			"Customer",
			or_filters={
				"name": ["like", f"%{query}%"],
				"customer_name": ["like", f"%{query}%"],
				"email_id": ["like", f"%{query}%"],
			},
			fields=["name", "customer_name", "email_id", "mobile_no"],
			limit=limit,
			order_by="modified desc",
		)
		return [self._customer(row) for row in rows]

	def list_sites(self, customer_id: str) -> list[SiteRecord]:
		links = self._get_all(
			"Dynamic Link",
			filters={"link_doctype": "Customer", "link_name": customer_id, "parenttype": "Address"},
			fields=["parent"],
			limit=100,
		)
		names = [row.parent for row in links]
		if not names:
			return []
		rows = self._get_all(
			"Address",
			filters={"name": ["in", names]},
			fields=["name", "address_title", "address_line1", "city", "state", "pincode"],
			limit=100,
		)
		return [
			SiteRecord(
				id=row.name,
				customer_id=customer_id,
				title=row.address_title or row.name,
				address_line1=row.address_line1,
				city=row.city,
				state=row.state,
				postal_code=row.pincode,
			)
			for row in rows
		]

	def list_equipment(self, customer_id: str) -> list[EquipmentRecord]:
		rows = self._get_all(
			"Serial No",
			filters={"customer": customer_id},
			fields=["name", "item_code", "warranty_expiry_date"],
			limit=500,
			order_by="modified desc",
		)
		return [
			EquipmentRecord(
				id=row.name,
				customer_id=customer_id,
				item_code=row.item_code,
				serial_number=row.name,
				warranty_expiry=row.warranty_expiry_date,
			)
			for row in rows
		]

	def list_service_visits(self, customer_id: str, limit: int = 20) -> list[ServiceVisitRecord]:
		rows = self._get_all(
			"Maintenance Visit",
			filters={"customer": customer_id},
			fields=["name", "mntc_date", "status", "maintenance_type"],
			limit=max(1, min(limit, 100)),
			order_by="mntc_date desc, modified desc",
		)
		return [
			ServiceVisitRecord(row.name, customer_id, row.mntc_date, row.status, row.maintenance_type)
			for row in rows
		]

	def list_quotes(self, customer_id: str, limit: int = 20) -> list[QuoteRecord]:
		rows = self._get_all(
			"Quotation",
			filters={"quotation_to": "Customer", "party_name": customer_id},
			fields=["name", "status", "grand_total", "currency"],
			limit=max(1, min(limit, 100)),
			order_by="transaction_date desc, modified desc",
		)
		return [
			QuoteRecord(row.name, customer_id, row.status, _decimal(row.grand_total), row.currency)
			for row in rows
		]

	def list_invoices(self, customer_id: str, limit: int = 20) -> list[InvoiceRecord]:
		rows = self._get_all(
			"Sales Invoice",
			filters={"customer": customer_id, "docstatus": ["!=", 2]},
			fields=["name", "status", "outstanding_amount", "currency"],
			limit=max(1, min(limit, 100)),
			order_by="posting_date desc, modified desc",
		)
		return [
			InvoiceRecord(row.name, customer_id, row.status, _decimal(row.outstanding_amount), row.currency)
			for row in rows
		]

	@staticmethod
	def _customer(row) -> CustomerRecord:
		return CustomerRecord(
			id=row.name,
			name=row.customer_name or row.name,
			email=row.email_id,
			phone=row.mobile_no,
		)
