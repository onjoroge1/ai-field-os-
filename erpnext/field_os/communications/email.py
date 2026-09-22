"""Email provider boundary and approved email workflow."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

import frappe

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt, RiskClass
from erpnext.field_os.actions.validation import require_proposal
from erpnext.field_os.ai.conversation import ProposalStore
from erpnext.field_os.communications.approval import message_digest
from erpnext.field_os.communications.models import (
	CommunicationAttachment,
	CommunicationChannel,
	CommunicationMessage,
	CommunicationParticipant,
	CommunicationThread,
	DeliveryState,
	EntityLinks,
	IngestResult,
	MessageDirection,
	ParticipantRole,
	ThreadState,
)
from erpnext.field_os.communications.ordering import accept_delivery
from erpnext.field_os.communications.repository import CommunicationRepository
from erpnext.field_os.communications.service import CommunicationService, normalize_address
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


@dataclass(frozen=True, slots=True)
class InboundEmail:
	external_id: str
	external_thread_id: str
	from_address: str
	from_name: str | None
	to: tuple[str, ...]
	cc: tuple[str, ...]
	subject: str
	body: str
	received_at: datetime
	attachments: tuple[CommunicationAttachment, ...] = ()
	metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class OutboundEmail:
	from_address: str
	to: tuple[str, ...]
	cc: tuple[str, ...]
	subject: str
	body: str
	idempotency_key: str
	reference_id: str


@dataclass(frozen=True, slots=True)
class EmailSendResult:
	external_id: str
	state: DeliveryState
	accepted_at: datetime
	metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EmailDeliveryEvent:
	external_id: str
	state: DeliveryState
	occurred_at: datetime
	error: str | None = None
	metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EmailClassification:
	category: str
	priority: str
	confidence: float


class EmailProvider(Protocol):
	def verify_and_parse_inbound(self, raw_body: bytes, headers: dict[str, str], secret: str) -> InboundEmail:
		...

	def verify_and_parse_delivery(
		self, raw_body: bytes, headers: dict[str, str], secret: str
	) -> EmailDeliveryEvent:
		...

	def send(self, email: OutboundEmail) -> EmailSendResult:
		...

	def poll(self, cursor: str | None, limit: int) -> tuple[list[InboundEmail], str | None]:
		...


class EmailClassifier(Protocol):
	def classify(self, subject: str, body: str) -> EmailClassification:
		...


class EmailEntityResolver(Protocol):
	def resolve(self, company: str, sender_address: str) -> EntityLinks:
		...


class DeterministicEmailClassifier:
	def classify(self, subject: str, body: str) -> EmailClassification:
		text = f"{subject} {body}".lower()
		if any(term in text for term in ("gas leak", "smoke", "sparking", "carbon monoxide")):
			return EmailClassification("safety_emergency", "urgent", 1.0)
		if any(term in text for term in ("no cooling", "not cooling", "no heat", "broken", "leak")):
			return EmailClassification("service_request", "high", 0.9)
		if any(term in text for term in ("invoice", "balance", "payment")):
			return EmailClassification("billing", "normal", 0.85)
		return EmailClassification("general", "normal", 0.6)


class FrappeEmailProvider:
	"""Signed normalized webhook plus ERPNext's configured outbound mailer.

	Provider-specific adapters can implement the same protocol and be selected by
	the integration record without changing the workflow.
	"""

	def verify_and_parse_inbound(self, raw_body, headers, secret):
		self._verify(raw_body, headers, secret)
		payload = json.loads(raw_body)
		return InboundEmail(
			external_id=str(payload["id"]),
			external_thread_id=str(payload.get("thread_id") or payload["id"]),
			from_address=str(payload["from"]["address"]),
			from_name=payload["from"].get("name"),
			to=tuple(str(item) for item in payload.get("to", [])),
			cc=tuple(str(item) for item in payload.get("cc", [])),
			subject=str(payload.get("subject") or "(no subject)"),
			body=str(payload.get("text") or ""),
			received_at=datetime.fromisoformat(payload["received_at"]),
			attachments=tuple(
				CommunicationAttachment(
					str(item["filename"]),
					str(item.get("content_type") or "application/octet-stream"),
					int(item.get("size_bytes") or 0),
					external_url=item.get("url"),
				)
				for item in payload.get("attachments", [])
			),
			metadata=payload.get("metadata") or {},
		)

	def verify_and_parse_delivery(self, raw_body, headers, secret):
		self._verify(raw_body, headers, secret)
		payload = json.loads(raw_body)
		state = DeliveryState(str(payload["state"]).lower())
		if state not in {
			DeliveryState.SENT,
			DeliveryState.DELIVERED,
			DeliveryState.FAILED,
			DeliveryState.BOUNCED,
		}:
			raise ValueError("Unsupported email delivery state")
		return EmailDeliveryEvent(
			str(payload["id"]),
			state,
			datetime.fromisoformat(payload["occurred_at"]),
			payload.get("error"),
			payload.get("metadata") or {},
		)

	def send(self, email):
		frappe.sendmail(
			recipients=list(email.to),
			cc=list(email.cc),
			sender=email.from_address,
			subject=email.subject,
			message=email.body,
			reference_doctype="Field OS Communication Message",
			reference_name=email.reference_id,
			now=False,
		)
		return EmailSendResult(
			f"frappe:{email.reference_id}:{hashlib.sha256(email.idempotency_key.encode()).hexdigest()[:24]}",
			DeliveryState.QUEUED,
			datetime.now(UTC),
		)

	def poll(self, cursor, limit):
		return [], cursor

	@staticmethod
	def _verify(raw_body: bytes, headers: dict[str, str], secret: str) -> None:
		provided = headers.get("X-Field-OS-Signature") or headers.get("x-field-os-signature") or ""
		expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
		if not secret or not hmac.compare_digest(provided.removeprefix("sha256="), expected):
			raise PermissionError("Invalid email webhook signature")


class EmailService:
	def __init__(
		self,
		repository: CommunicationRepository,
		classifier: EmailClassifier,
		resolver: EmailEntityResolver,
		proposals: ProposalStore | None = None,
	) -> None:
		self.repository = repository
		self.communications = CommunicationService(repository)
		self.classifier = classifier
		self.resolver = resolver
		self.proposals = proposals

	def receive(self, company: str, integration_id: str, email: InboundEmail) -> IngestResult:
		previous = self.repository.find_message_by_dedupe(company, f"{integration_id}:{email.external_id}")
		if previous:
			return IngestResult(self.repository.get_thread(company, previous.thread_id), previous, False)
		classification = self.classifier.classify(email.subject, email.body)
		links = self.resolver.resolve(company, email.from_address)
		sender = CommunicationParticipant(
			normalize_address(CommunicationChannel.EMAIL, email.from_address),
			ParticipantRole.CUSTOMER if links.customer_id else ParticipantRole.EXTERNAL,
			email.from_name,
		)
		participants = (
			sender,
			*tuple(
				CommunicationParticipant(
					normalize_address(CommunicationChannel.EMAIL, address), ParticipantRole.USER
				)
				for address in (*email.to, *email.cc)
			),
		)
		sla_minutes = {"urgent": 15, "high": 60, "normal": 240}.get(classification.priority, 240)
		thread = CommunicationThread(
			None,
			company,
			email.subject,
			CommunicationChannel.EMAIL,
			ThreadState.OPEN,
			participants,
			links,
			classification=classification.category,
			sla_due_at=email.received_at + timedelta(minutes=sla_minutes),
			external_thread_id=f"{integration_id}:{email.external_thread_id}",
		)
		message = CommunicationMessage(
			None,
			company,
			None,
			CommunicationChannel.EMAIL,
			MessageDirection.INBOUND,
			sender,
			participants[1:],
			email.body,
			email.received_at,
			DeliveryState.RECEIVED,
			email.subject,
			email.external_id,
			f"{integration_id}:{email.external_id}",
			integration_id,
			email.attachments,
			classification.category,
			email.metadata or {},
		)
		return self.communications.ingest(thread, message)

	def draft(
		self,
		context: TenantContext,
		thread_id: str,
		integration_id: str,
		from_address: str,
		to: tuple[str, ...],
		cc: tuple[str, ...],
		subject: str,
		body: str,
	) -> CommunicationMessage:
		if not to:
			raise ValueError("At least one recipient is required")
		message = CommunicationMessage(
			None,
			context.company,
			thread_id,
			CommunicationChannel.EMAIL,
			MessageDirection.OUTBOUND,
			CommunicationParticipant(from_address, ParticipantRole.USER, context.user),
			tuple(
				CommunicationParticipant(
					normalize_address(CommunicationChannel.EMAIL, address), ParticipantRole.CUSTOMER
				)
				for address in (*to, *cc)
			),
			body.strip(),
			datetime.now(UTC),
			DeliveryState.DRAFT,
			subject.strip(),
			provider=integration_id,
		)
		if not message.body:
			raise ValueError("Email body is required")
		return self.communications.create_draft(context, message)

	def preview_send(self, context: TenantContext, message_id: str) -> ActionProposal:
		authorize(context, "communicate")
		message = self.repository.get_message(context.company, message_id)
		if message is None or message.channel != CommunicationChannel.EMAIL:
			raise ValueError("Email draft was not found")
		if message.delivery_state not in {DeliveryState.DRAFT, DeliveryState.FAILED}:
			raise ValueError("Only draft or failed email can be sent")
		for recipient in message.recipients:
			if not self.communications.can_send(
				context.company, recipient.address, CommunicationChannel.EMAIL, transactional=True
			):
				raise PermissionError(f"Recipient has opted out: {recipient.address}")
		now = datetime.now(UTC)
		proposal = ActionProposal(
			str(uuid4()),
			"send_email",
			{"message_id": message.id, "message_digest": message_digest(message)},
			RiskClass.EXTERNAL,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=10),
		)
		if not self.proposals:
			raise ValueError("Proposal storage is not configured")
		self.proposals.save(proposal)
		self.repository.save_message(replace(message, delivery_state=DeliveryState.PENDING_APPROVAL))
		return proposal

	def approve_send(
		self,
		context: TenantContext,
		proposal_id: str,
		idempotency_key: str,
		provider: EmailProvider,
		integration_id: str,
		from_address: str,
		engine: ActionEngine,
	) -> ExecutionReceipt:
		authorize(context, "communicate")
		if not self.proposals:
			raise ValueError("Proposal storage is not configured")
		proposal = self.proposals.load(context.company, proposal_id)
		proposal = require_proposal(proposal, context, tool="send_email", risk=RiskClass.EXTERNAL)
		message = self.repository.get_message(context.company, str(proposal.arguments["message_id"]))
		if message is None or message.delivery_state != DeliveryState.PENDING_APPROVAL:
			raise ValueError("Email is no longer pending approval")
		if proposal.arguments.get("message_digest") != message_digest(message):
			raise ValueError("Message changed after preview; generate a new approval")
		if message.sender.address != from_address:
			raise ValueError("Sender changed after preview; generate a new approval")
		if message.provider != integration_id:
			raise PermissionError("Email provider integration does not match the approved draft")

		for recipient in message.recipients:
			if not self.communications.can_send(
				context.company, recipient.address, CommunicationChannel.EMAIL, transactional=True
			):
				raise PermissionError("Email consent changed; sending is blocked")

		def execute():
			queued = self.repository.save_message(
				replace(message, delivery_state=DeliveryState.QUEUED, error=None)
			)
			addresses = tuple(item.address for item in queued.recipients)
			try:
				result = provider.send(
					OutboundEmail(
						from_address,
						addresses,
						(),
						queued.subject or "",
						queued.body,
						idempotency_key,
						queued.id or "",
					)
				)
			except Exception as exc:
				self.repository.save_message(
					replace(
						queued,
						delivery_state=DeliveryState.FAILED,
						error=type(exc).__name__ + ": delivery failed",
					)
				)
				raise
			sent = self.repository.save_message(
				replace(
					queued,
					delivery_state=result.state,
					external_id=result.external_id,
					metadata=result.metadata or {},
				)
			)
			return {
				"message_id": sent.id,
				"external_id": sent.external_id,
				"state": sent.delivery_state.value,
			}

		receipt = engine.execute(proposal, idempotency_key, execute, approved_by=context.user)
		self.proposals.delete(context.company, proposal_id)
		return receipt

	def apply_delivery_event(
		self, company: str, integration_id: str, event: EmailDeliveryEvent
	) -> CommunicationMessage:
		message = self.repository.find_message_by_external_id(
			company, CommunicationChannel.EMAIL, event.external_id, integration_id
		)
		if message is None:
			raise ValueError("Delivery event references an unknown email")
		if not accept_delivery(message, event):
			return message
		metadata = {
			**message.metadata,
			**(event.metadata or {}),
			"delivery_event_at": event.occurred_at.isoformat(),
		}
		return self.repository.save_message(
			replace(message, delivery_state=event.state, error=event.error, metadata=metadata)
		)
