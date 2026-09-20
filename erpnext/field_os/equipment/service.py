from datetime import UTC, datetime
from typing import Protocol

from erpnext.field_os.equipment.models import EquipmentHistory, EquipmentNote, HVACEquipment
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


class EquipmentRepository(Protocol):
	def list_equipment(self, company: str, customer_id: str) -> list[HVACEquipment]:
		...

	def get_equipment(self, company: str, equipment_id: str) -> HVACEquipment:
		...

	def list_notes(self, company: str, equipment_id: str) -> list[EquipmentNote]:
		...

	def create_note(
		self,
		company: str,
		equipment_id: str,
		technician: str,
		note: str,
		occurred_at: datetime,
		visit_id: str | None,
		photo_urls: tuple[str, ...],
	) -> EquipmentNote:
		...


class EquipmentService:
	def __init__(self, repository: EquipmentRepository) -> None:
		self.repository = repository

	def history(self, context: TenantContext, equipment_id: str) -> EquipmentHistory:
		authorize(context, "read")
		equipment = self.repository.get_equipment(context.company, equipment_id)
		items = self.repository.list_equipment(context.company, equipment.customer_id)
		by_id = {item.id: item for item in items}
		ancestors, seen, parent_id = [], {equipment.id}, equipment.parent_id
		while parent_id:
			if parent_id in seen:
				raise ValueError("Equipment hierarchy contains a cycle")
			seen.add(parent_id)
			parent = by_id.get(parent_id)
			if not parent:
				break
			ancestors.append(parent)
			parent_id = parent.parent_id
		return EquipmentHistory(
			equipment,
			tuple(ancestors),
			tuple(x for x in items if x.parent_id == equipment.id),
			tuple(self.repository.list_notes(context.company, equipment.id)),
		)

	def add_note(
		self,
		context: TenantContext,
		equipment_id: str,
		note: str,
		visit_id: str | None = None,
		photo_urls: tuple[str, ...] = (),
	) -> EquipmentNote:
		authorize(context, "field_update")
		if not note.strip() or len(photo_urls) > 20:
			raise ValueError("A note and no more than 20 photos are required")
		self.repository.get_equipment(context.company, equipment_id)
		return self.repository.create_note(
			context.company, equipment_id, context.user, note.strip(), datetime.now(UTC), visit_id, photo_urls
		)
