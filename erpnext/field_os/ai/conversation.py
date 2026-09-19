"""Safe conversational interface over the registered Field OS tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt, RiskClass
from erpnext.field_os.ai.intent import parse_tool_call
from erpnext.field_os.ai.provider import ModelMessage, ModelProvider
from erpnext.field_os.ai.tools import ToolRegistry
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


class ConversationRetention(StrEnum):
	NONE = "none"
	SESSION = "session"
	THIRTY_DAYS = "30_days"


@dataclass(frozen=True, slots=True)
class Citation:
	label: str
	doctype: str
	record_id: str


@dataclass(frozen=True, slots=True)
class ToolOutput:
	data: Any
	citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ApprovalCard:
	proposal_id: str
	tool: str
	risk: RiskClass
	title: str
	arguments: dict[str, Any]
	expires_at: datetime


@dataclass(frozen=True, slots=True)
class AskResponse:
	conversation_id: str
	answer: str
	citations: tuple[Citation, ...] = ()
	approval: ApprovalCard | None = None
	retryable: bool = False


class ConversationStore(Protocol):
	def load(self, company: str, user: str, conversation_id: str) -> tuple[ModelMessage, ...]:
		...

	def save(
		self,
		company: str,
		user: str,
		conversation_id: str,
		messages: tuple[ModelMessage, ...],
		retention: ConversationRetention,
	) -> None:
		...

	def clear(self, company: str, user: str, conversation_id: str) -> None:
		...


class ProposalStore(Protocol):
	def save(self, proposal: ActionProposal) -> None:
		...

	def load(self, company: str, proposal_id: str) -> ActionProposal | None:
		...

	def delete(self, company: str, proposal_id: str) -> None:
		...


class MemoryConversationStore:
	def __init__(self) -> None:
		self.messages: dict[tuple[str, str, str], tuple[ModelMessage, ...]] = {}

	def load(self, company, user, conversation_id):
		return self.messages.get((company, user, conversation_id), ())

	def save(self, company, user, conversation_id, messages, retention):
		key = (company, user, conversation_id)
		if retention == ConversationRetention.NONE:
			self.messages.pop(key, None)
		else:
			self.messages[key] = messages

	def clear(self, company, user, conversation_id):
		self.messages.pop((company, user, conversation_id), None)


class AskOperationsService:
	def __init__(
		self,
		provider: ModelProvider,
		registry: ToolRegistry,
		conversations: ConversationStore,
		proposals: ProposalStore | None = None,
	) -> None:
		self.provider = provider
		self.registry = registry
		self.conversations = conversations
		self.proposals = proposals

	def ask(
		self,
		context: TenantContext,
		message: str,
		*,
		conversation_id: str | None = None,
		retention: ConversationRetention = ConversationRetention.SESSION,
	) -> AskResponse:
		authorize(context, "read")
		message = message.strip()
		if not message:
			raise ValueError("Message is required")
		if len(message) > 4000:
			raise ValueError("Message exceeds the 4,000 character limit")

		conversation_id = conversation_id or str(uuid4())
		history = self.conversations.load(context.company, context.user, conversation_id)[-20:]
		request_messages = (*history, ModelMessage("user", message))
		reply = self.provider.respond(request_messages, self.registry.manifest())

		citations: tuple[Citation, ...] = ()
		approval = None
		answer = reply.answer.strip()
		if reply.tool_call is not None:
			call = parse_tool_call(reply.tool_call)
			definition = self.registry.get(call.tool)
			if definition.risk == RiskClass.READ:
				result = self.registry.invoke(context, call.tool, call.arguments)
				output = result if isinstance(result, ToolOutput) else ToolOutput(result)
				citations = output.citations
				if not answer:
					answer = self._summarize(output.data)
			else:
				authorize(context, definition.capability)
				self._validate_preview(call.tool, call.arguments)
				now = datetime.now(UTC)
				proposal = ActionProposal(
					id=str(uuid4()),
					tool=call.tool,
					arguments=call.arguments,
					risk=definition.risk,
					company=context.company,
					actor=context.user,
					created_at=now,
					expires_at=now + timedelta(minutes=10),
				)
				if self.proposals:
					self.proposals.save(proposal)
				approval = ApprovalCard(
					proposal.id,
					proposal.tool,
					proposal.risk,
					answer or f"Approve {proposal.tool.replace('_', ' ')}?",
					proposal.arguments,
					proposal.expires_at,
				)
				answer = answer or "Review this action before it runs."

		updated = (*request_messages, ModelMessage("assistant", answer))
		self.conversations.save(context.company, context.user, conversation_id, updated, retention)
		return AskResponse(conversation_id, answer, citations, approval)

	def clear(self, context: TenantContext, conversation_id: str) -> None:
		authorize(context, "read")
		self.conversations.clear(context.company, context.user, conversation_id)

	def approve(
		self,
		context: TenantContext,
		proposal_id: str,
		idempotency_key: str,
		action_engine: ActionEngine,
	) -> ExecutionReceipt:
		if not self.proposals:
			raise ValueError("Proposal storage is not configured")
		proposal = self.proposals.load(context.company, proposal_id)
		if proposal is None:
			raise ValueError("Proposal is missing or expired")
		definition = self.registry.get(proposal.tool)
		authorize(context, definition.capability)
		receipt = action_engine.execute(
			proposal,
			idempotency_key,
			lambda: self.registry.invoke(context, proposal.tool, proposal.arguments),
			approved_by=context.user,
		)
		self.proposals.delete(context.company, proposal.id)
		return receipt

	def reject(self, context: TenantContext, proposal_id: str) -> None:
		if not self.proposals:
			raise ValueError("Proposal storage is not configured")
		proposal = self.proposals.load(context.company, proposal_id)
		if proposal is None:
			raise ValueError("Proposal is missing or expired")
		definition = self.registry.get(proposal.tool)
		authorize(context, definition.capability)
		self.proposals.delete(context.company, proposal_id)

	def _validate_preview(self, name: str, arguments: dict[str, Any]) -> None:
		definition = self.registry.get(name)
		missing = definition.required_fields - arguments.keys()
		unexpected = arguments.keys() - definition.required_fields - definition.optional_fields
		if missing:
			raise ValueError(f"Missing required fields for {name}: {', '.join(sorted(missing))}")
		if unexpected:
			raise ValueError(f"Unexpected fields for {name}: {', '.join(sorted(unexpected))}")

	@staticmethod
	def _summarize(data: Any) -> str:
		if data is None or data == []:
			return "I did not find any matching records."
		if isinstance(data, list | tuple):
			return f"I found {len(data)} matching record{'s' if len(data) != 1 else ''}."
		return "I found the requested operational record."
