"""Model-provider boundary for Ask Operations.

Provider implementations receive only the bounded conversation and registered
tool manifest. They do not receive database handles or executable functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModelProviderUnavailable(RuntimeError):
	pass


@dataclass(frozen=True, slots=True)
class ModelMessage:
	role: str
	content: str


@dataclass(frozen=True, slots=True)
class ModelReply:
	answer: str
	tool_call: dict[str, Any] | None = None
	model: str | None = None
	input_tokens: int | None = None
	output_tokens: int | None = None


class ModelProvider(Protocol):
	def respond(
		self,
		messages: tuple[ModelMessage, ...],
		tools: tuple[dict[str, Any], ...],
	) -> ModelReply:
		...


class DisabledModelProvider:
	def respond(self, messages, tools) -> ModelReply:
		raise ModelProviderUnavailable(
			"Ask Operations needs a configured FIELD_OS_MODEL_PROVIDER implementation."
		)
