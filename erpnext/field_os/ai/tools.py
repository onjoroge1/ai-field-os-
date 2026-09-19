"""Schema-bound tool registry for AI Field OS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

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


class ToolRegistry:
	def __init__(self) -> None:
		self._tools: dict[str, ToolDefinition] = {}

	def register(self, tool: ToolDefinition) -> None:
		if tool.name in self._tools:
			raise ValueError(f"Tool already registered: {tool.name}")
		self._tools[tool.name] = tool

	def names(self) -> tuple[str, ...]:
		return tuple(sorted(self._tools))

	def invoke(self, context: TenantContext, name: str, arguments: dict[str, Any]) -> Any:
		tool = self._tools.get(name)
		if tool is None:
			raise ToolValidationError(f"Unknown tool: {name}")
		authorize(context, tool.capability)
		missing = tool.required_fields - arguments.keys()
		if missing:
			raise ToolValidationError(f"Missing required fields for {name}: {', '.join(sorted(missing))}")
		return tool.handler(context, dict(arguments))
