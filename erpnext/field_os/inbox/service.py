"""Triage, assignment, SLA, suggestions, and correction feedback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt, RiskClass
from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationThread,
	DeliveryState,
	MessageDirection,
	ThreadState,
)
from erpnext.field_os.communications.repository import CommunicationRepository
from erpnext.field_os.inbox.models import (
	CorrectionFeedback,
	InboxDetail,
	InboxItem,
	InboxQueue,
	SLAState,
	SuggestedAction,
)
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


class CorrectionStore(Protocol):
	def save(self, feedback: CorrectionFeedback) -> CorrectionFeedback:
		...


class CorrectionPolicy(Protocol):
	def validate(self, company: str, thread: CommunicationThread, field: str, value: str) -> None:
		...


class AssigneePolicy(Protocol):
	def validate(self, company: str, user: str) -> None:
		...


class ServiceRequestCreator(Protocol):
	def create(self, context: TenantContext, thread: CommunicationThread, summary: str) -> str:
		...


class InboxService:
	def __init__(
		self,
		repository: CommunicationRepository,
		corrections: CorrectionStore,
		correction_policy: CorrectionPolicy,
		assignee_policy: AssigneePolicy,
		request_creator: ServiceRequestCreator,
	) -> None:
		self.repository = repository
		self.corrections = corrections
		self.correction_policy = correction_policy
		self.assignee_policy = assignee_policy
		self.request_creator = request_creator

	def queue(
		self,
		context: TenantContext,
		*,
		states: tuple[ThreadState, ...] = (ThreadState.OPEN, ThreadState.PENDING),
		channel: CommunicationChannel | None = None,
		assigned_to: str | None = None,
		limit: int = 50,
		now: datetime | None = None,
	) -> InboxQueue:
		authorize(context, "communicate")
		now = now or datetime.now(UTC)
		if not now.tzinfo:
			now = now.replace(tzinfo=UTC)
		threads = self.repository.list_threads(
			context.company,
			states=tuple(state.value for state in states),
			channel=channel,
			assigned_to=assigned_to,
			limit=max(1, min(limit, 100)),
		)
		items = [self._item(context, thread, now) for thread in threads]
		priority = {SLAState.OVERDUE: 0, SLAState.DUE_SOON: 1, SLAState.ON_TRACK: 2, SLAState.NONE: 3}
		items.sort(
			key=lambda item: (
				priority[item.sla_state],
				-(self._aware(item.thread.last_message_at).timestamp() if item.thread.last_message_at else 0),
			)
		)
		counts = {"total": len(items), "unassigned": 0}
		for item in items:
			counts[item.sla_state.value] = counts.get(item.sla_state.value, 0) + 1
			if not item.thread.assigned_to:
				counts["unassigned"] += 1
		return InboxQueue(tuple(items), counts)

	def detail(self, context: TenantContext, thread_id: str) -> InboxDetail:
		authorize(context, "communicate")
		thread = self._thread(context, thread_id)
		messages = tuple(self.repository.list_messages(context.company, thread_id, limit=500))
		return InboxDetail(
			thread, messages, self._suggestions(context, thread, messages[-1] if messages else None)
		)

	def assign(
		self,
		context: TenantContext,
		thread_id: str,
		user: str,
		idempotency_key: str,
		engine: ActionEngine,
	) -> ExecutionReceipt:
		authorize(context, "communicate")
		thread = self._thread(context, thread_id)
		self.assignee_policy.validate(context.company, user)
		proposal = self._proposal(context, "assign_inbox_thread", {"thread_id": thread_id, "user": user})

		def execute():
			updated = self.repository.save_thread(replace(thread, assigned_to=user))
			return {"thread_id": updated.id, "assigned_to": updated.assigned_to}

		return engine.execute(proposal, idempotency_key, execute, approved_by=context.user)

	def set_state(
		self,
		context: TenantContext,
		thread_id: str,
		state: ThreadState,
		idempotency_key: str,
		engine: ActionEngine,
	) -> ExecutionReceipt:
		authorize(context, "communicate")
		thread = self._thread(context, thread_id)
		proposal = self._proposal(
			context, "set_inbox_thread_state", {"thread_id": thread_id, "state": state.value}
		)

		def execute():
			updated = self.repository.save_thread(replace(thread, state=state))
			return {"thread_id": updated.id, "state": updated.state.value}

		return engine.execute(proposal, idempotency_key, execute, approved_by=context.user)

	def correct(
		self,
		context: TenantContext,
		thread_id: str,
		field: str,
		value: str,
		*,
		reason: str | None = None,
		message_id: str | None = None,
	) -> CorrectionFeedback:
		authorize(context, "communicate")
		thread = self._thread(context, thread_id)
		value = value.strip()
		if not value:
			raise ValueError("Correction value is required")
		if message_id:
			message = self.repository.get_message(context.company, message_id)
			if message is None or message.thread_id != thread_id:
				raise ValueError("Correction message was not found in this Inbox thread")
		self.correction_policy.validate(context.company, thread, field, value)
		previous = self._field_value(thread, field)
		updated = self._replace_field(thread, field, value)
		self.repository.save_thread(updated)
		return self.corrections.save(
			CorrectionFeedback(
				context.company,
				thread_id,
				field,
				previous,
				value,
				context.user,
				datetime.now(UTC),
				reason.strip() if reason else None,
				message_id,
			)
		)

	def create_service_request(
		self,
		context: TenantContext,
		thread_id: str,
		idempotency_key: str,
		engine: ActionEngine,
	) -> ExecutionReceipt:
		authorize(context, "dispatch")
		thread = self._thread(context, thread_id)
		if thread.links.service_request_id:
			raise ValueError("Thread already has a service request")
		if not thread.links.customer_id:
			raise ValueError("Link a customer before creating a service request")
		messages = self.repository.list_messages(context.company, thread_id, limit=100)
		summary = messages[-1].body if messages else thread.subject
		proposal = self._proposal(context, "create_service_request", {"thread_id": thread_id})

		def execute():
			request_id = self.request_creator.create(context, thread, summary)
			updated_links = replace(thread.links, service_request_id=request_id)
			self.repository.save_thread(replace(thread, links=updated_links))
			return {"thread_id": thread_id, "service_request_id": request_id}

		return engine.execute(proposal, idempotency_key, execute, approved_by=context.user)

	def _item(self, context: TenantContext, thread: CommunicationThread, now: datetime) -> InboxItem:
		messages = self.repository.list_messages(context.company, thread.id or "", limit=100)
		latest = messages[-1] if messages else None
		last_at = self._aware(latest.occurred_at if latest else thread.last_message_at)
		age = max(0, int((now - last_at).total_seconds())) if last_at else 0
		return InboxItem(
			thread, latest, age, self._sla(thread, now), self._suggestions(context, thread, latest)
		)

	@staticmethod
	def _sla(thread: CommunicationThread, now: datetime) -> SLAState:
		if not thread.sla_due_at:
			return SLAState.NONE
		due_at = InboxService._aware(thread.sla_due_at)
		if due_at <= now:
			return SLAState.OVERDUE
		if due_at <= now + timedelta(minutes=30):
			return SLAState.DUE_SOON
		return SLAState.ON_TRACK

	@staticmethod
	def _aware(value: datetime | None) -> datetime | None:
		if value is None:
			return None
		return value if value.tzinfo else value.replace(tzinfo=UTC)

	@staticmethod
	def _suggestions(
		context: TenantContext, thread: CommunicationThread, latest
	) -> tuple[SuggestedAction, ...]:
		actions = []
		if not thread.assigned_to:
			actions.append(SuggestedAction("assign_me", "Assign to me", "assign", {"user": context.user}))
		if (
			latest
			and latest.direction == MessageDirection.INBOUND
			and thread.channel in {CommunicationChannel.EMAIL, CommunicationChannel.SMS}
		):
			actions.append(SuggestedAction("reply", f"Reply by {thread.channel.value.upper()}", "reply", {}))
		if not thread.links.customer_id:
			actions.append(
				SuggestedAction("link_customer", "Link customer", "correct", {"field": "customer_id"})
			)
		if (
			thread.classification == "service_request"
			and thread.links.customer_id
			and not thread.links.service_request_id
		):
			actions.append(SuggestedAction("create_request", "Create service request", "create_request", {}))
		if thread.classification == "safety_emergency":
			actions.insert(0, SuggestedAction("escalate", "Escalate safety issue", "escalate", {}))
		if latest and latest.delivery_state in {DeliveryState.FAILED, DeliveryState.BOUNCED}:
			actions.append(
				SuggestedAction(
					"retry_delivery", "Review failed delivery", "open_message", {"message_id": latest.id}
				)
			)
		return tuple(actions)

	@staticmethod
	def _proposal(context: TenantContext, tool: str, arguments: dict) -> ActionProposal:
		now = datetime.now(UTC)
		return ActionProposal(
			str(uuid4()),
			tool,
			arguments,
			RiskClass.LOW,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=5),
		)

	def _thread(self, context: TenantContext, thread_id: str) -> CommunicationThread:
		thread = self.repository.get_thread(context.company, thread_id)
		if thread is None:
			raise ValueError("Inbox thread was not found")
		return thread

	@staticmethod
	def _field_value(thread: CommunicationThread, field: str) -> str | None:
		if field == "classification":
			return thread.classification
		if not hasattr(thread.links, field):
			raise ValueError("Unsupported correction field")
		return getattr(thread.links, field)

	@staticmethod
	def _replace_field(thread: CommunicationThread, field: str, value: str) -> CommunicationThread:
		if field == "classification":
			return replace(thread, classification=value)
		if not hasattr(thread.links, field):
			raise ValueError("Unsupported correction field")
		return replace(thread, links=replace(thread.links, **{field: value}))
