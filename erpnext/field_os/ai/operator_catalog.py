"""Tool catalog with citations suitable for Ask Operations."""

from __future__ import annotations

from erpnext.field_os.adapter.base import FieldOperationsAdapter
from erpnext.field_os.ai.conversation import Citation, ToolOutput
from erpnext.field_os.ai.tools import ToolDefinition, ToolRegistry


def build_operator_registry(adapter: FieldOperationsAdapter) -> ToolRegistry:
	registry = ToolRegistry()

	def find_customer(_context, args):
		rows = adapter.find_customers(str(args["query"]), int(args.get("limit", 10)))
		return ToolOutput(
			rows,
			tuple(Citation(row.name, "Customer", row.id) for row in rows),
		)

	def equipment(_context, args):
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
			"List equipment registered to a customer.",
			"read",
			frozenset({"customer_id"}),
			equipment,
		)
	)
	return registry
