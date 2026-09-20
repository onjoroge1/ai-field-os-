"""Tool catalog with citations suitable for Ask Operations."""

from __future__ import annotations

from erpnext.field_os.adapter.base import FieldOperationsAdapter
from erpnext.field_os.ai.conversation import Citation, ToolOutput
from erpnext.field_os.ai.tools import ToolDefinition, ToolRegistry
from erpnext.field_os.equipment.service import EquipmentService


def build_operator_registry(adapter: FieldOperationsAdapter, equipment_repository=None) -> ToolRegistry:
	registry = ToolRegistry()

	def find_customer(_context, args):
		rows = adapter.find_customers(str(args["query"]), int(args.get("limit", 10)))
		return ToolOutput(
			rows,
			tuple(Citation(row.name, "Customer", row.id) for row in rows),
		)

	def equipment(context, args):
		if equipment_repository is not None:
			rows = equipment_repository.list_equipment(context.company, str(args["customer_id"]))
			return ToolOutput(
				tuple(EquipmentService(equipment_repository).history(context, row.id) for row in rows),
				tuple(Citation(row.name, "Field OS HVAC Equipment", row.id) for row in rows),
			)
		rows = adapter.list_equipment(str(args["customer_id"]))
		return ToolOutput(
			rows,
			tuple(Citation(row.serial_number, "Serial No", row.id) for row in rows),
		)

	registry.register(
		ToolDefinition(
			"find_customer",
			"Find a customer by name, email, or identifier.",
			"read",
			frozenset({"query"}),
			find_customer,
			optional_fields=frozenset({"limit"}),
		)
	)
	registry.register(
		ToolDefinition(
			"get_equipment_history",
			"Read equipment, hierarchy, warranties and technician service notes for a customer.",
			"read",
			frozenset({"customer_id"}),
			equipment,
		)
	)
	return registry
