"""Schema-bound tool registry for AI Field OS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


class ToolValidationError(ValueError):
	pass


@dataclass(frozen=True, slots=True)
class ToolDefinition:
	name: str
	description: str
	capability: str
	required_fields: frozenset[str]
	handler: Callable[[TenantContext, dict[str, Any]], Any]
	optional_fields: frozenset[str] = frozenset()
	risk: RiskClass = RiskClass.READ


class ToolRegistry:
	def __init__(self) -> None:
		self._tools: dict[str, ToolDefinition] = {}

	def register(self, tool: ToolDefinition) -> None:
		if tool.name in self._tools:
			raise ValueError(f"Tool already registered: {tool.name}")
		self._tools[tool.name] = tool

	def names(self) -> tuple[str, ...]:
		return tuple(sorted(self._tools))

	def get(self, name: str) -> ToolDefinition:
		tool = self._tools.get(name)
		if tool is None:
			raise ToolValidationError(f"Unknown tool: {name}")
		return tool

	def manifest(self) -> tuple[dict[str, Any], ...]:
		return tuple(
			{
				"name": tool.name,
				"description": tool.description,
				"required_fields": sorted(tool.required_fields),
				"optional_fields": sorted(tool.optional_fields),
				"risk": tool.risk.value,
			}
			for tool in sorted(self._tools.values(), key=lambda item: item.name)
		)

	def invoke(self, context: TenantContext, name: str, arguments: dict[str, Any]) -> Any:
		tool = self.get(name)
		authorize(context, tool.capability)
		missing = tool.required_fields - arguments.keys()
		if missing:
			raise ToolValidationError(f"Missing required fields for {name}: {', '.join(sorted(missing))}")
		unexpected = arguments.keys() - tool.required_fields - tool.optional_fields
		if unexpected:
			raise ToolValidationError(f"Unexpected fields for {name}: {', '.join(sorted(unexpected))}")
		return tool.handler(context, dict(arguments))
