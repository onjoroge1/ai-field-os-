from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class EstimateLine:
	item_code: str
	description: str
	quantity: Decimal
	rate: Decimal
	warehouse: str | None = None
	available_quantity: Decimal | None = None

	@property
	def amount(self):
		return self.quantity * self.rate


@dataclass(frozen=True, slots=True)
class Estimate:
	id: str
	company: str
	customer_id: str
	status: str
	currency: str
	valid_until: date | None
	lines: tuple[EstimateLine, ...]
	version: str | None = None

	@property
	def total(self):
		return sum((x.amount for x in self.lines), Decimal(0))
