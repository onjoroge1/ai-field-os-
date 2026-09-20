"""Strict parser for model-proposed tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProposedToolCall:
	tool: str
	arguments: dict[str, Any]


def parse_tool_call(payload: object) -> ProposedToolCall:
	if not isinstance(payload, dict):
		raise ValueError("Tool call must be an object")
	if set(payload) != {"tool", "arguments"}:
		raise ValueError("Tool call must contain only tool and arguments")
	tool = payload["tool"]
	arguments = payload["arguments"]
	if not isinstance(tool, str) or not tool.strip():
		raise ValueError("Tool name is required")
	if not isinstance(arguments, dict):
		raise ValueError("Tool arguments must be an object")
	return ProposedToolCall(tool=tool, arguments=arguments)
