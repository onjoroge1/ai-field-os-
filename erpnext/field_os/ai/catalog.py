"""Initial safe read-tool catalog."""

from __future__ import annotations

from erpnext.field_os.adapter.base import FieldOperationsAdapter
from erpnext.field_os.ai.tools import ToolDefinition, ToolRegistry


def build_read_registry(adapter: FieldOperationsAdapter) -> ToolRegistry:
	registry = ToolRegistry()
	registry.register(
		ToolDefinition(
			name="find_customer",
			description="Find customers by name or email.",
			capability="read",
			required_fields=frozenset({"query"}),
			handler=lambda _context, args: adapter.find_customers(str(args["query"])),
		)
	)
	registry.register(
		ToolDefinition(
			name="get_equipment_history",
			description="Get equipment registered to a customer.",
			capability="read",
			required_fields=frozenset({"customer_id"}),
			handler=lambda _context, args: adapter.list_equipment(str(args["customer_id"])),
		)
	)
	return registry
