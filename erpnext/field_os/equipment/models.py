from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class HVACEquipment:
	id: str
	company: str
	customer_id: str
	site_id: str
	name: str
	unit_type: str
	manufacturer: str | None = None
	model_number: str | None = None
	serial_number: str | None = None
	installed_on: date | None = None
	warranty_expires_on: date | None = None
	parent_id: str | None = None
	status: str = "Active"


@dataclass(frozen=True, slots=True)
class EquipmentNote:
	id: str
	company: str
	equipment_id: str
	technician: str
	note: str
	occurred_at: datetime
	visit_id: str | None = None
	photo_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EquipmentHistory:
	equipment: HVACEquipment
	ancestors: tuple[HVACEquipment, ...]
	children: tuple[HVACEquipment, ...]
	notes: tuple[EquipmentNote, ...]
