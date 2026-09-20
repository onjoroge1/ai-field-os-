"""Normalized records exposed to Field OS consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CustomerRecord:
	id: str
	name: str
	email: str | None = None
	phone: str | None = None


@dataclass(frozen=True, slots=True)
class SiteRecord:
	id: str
	customer_id: str
	title: str
	address_line1: str | None = None
	city: str | None = None
	state: str | None = None
	postal_code: str | None = None


@dataclass(frozen=True, slots=True)
class EquipmentRecord:
	id: str
	customer_id: str
	item_code: str
	serial_number: str
	warranty_expiry: date | None = None


@dataclass(frozen=True, slots=True)
class ServiceVisitRecord:
	id: str
	customer_id: str
	visit_date: date | None
	status: str
	maintenance_type: str | None = None


@dataclass(frozen=True, slots=True)
class QuoteRecord:
	id: str
	customer_id: str
	status: str
	total: Decimal
	currency: str
	transaction_date: date | None = None


@dataclass(frozen=True, slots=True)
class InvoiceRecord:
	id: str
	customer_id: str
	status: str
	outstanding_amount: Decimal
	currency: str
	posting_date: date | None = None
