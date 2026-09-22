"""SMS provider boundary, consent controls, templates, and approved sending."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt, RiskClass
from erpnext.field_os.actions.validation import require_proposal
from erpnext.field_os.ai.conversation import ProposalStore
from erpnext.field_os.communications.approval import message_digest
from erpnext.field_os.communications.email import EmailClassification, EmailClassifier
from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationMessage,
	CommunicationParticipant,
	CommunicationThread,
	ConsentState,
	ContactPreference,
	DeliveryState,
	EntityLinks,
	IngestResult,
	MessageDirection,
	ParticipantRole,
	ThreadState,
)
from erpnext.field_os.communications.ordering import accept_delivery, timestamp
from erpnext.field_os.communications.repository import CommunicationRepository
from erpnext.field_os.communications.service import CommunicationService, normalize_address
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext

STOP_WORDS = frozenset({"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"})
START_WORDS = frozenset({"START", "YES", "UNSTOP"})
_TEMPLATE_TOKEN = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*}}")


@dataclass(frozen=True, slots=True)
class InboundSMS:
	external_id: str
	from_number: str
	to_number: str
	body: str
	received_at: datetime
	external_thread_id: str | None = None
	metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class OutboundSMS:
	from_number: str
	to_number: str
	body: str
	idempotency_key: str
	reference_id: str


@dataclass(frozen=True, slots=True)
class SMSSendResult:
	external_id: str
	state: DeliveryState
	accepted_at: datetime
	metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SMSDeliveryEvent:
	external_id: str
	state: DeliveryState
	occurred_at: datetime
	error: str | None = None
	metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SMSReceiveResult:
	ingest: IngestResult
	consent_state: ConsentState | None = None


@dataclass(frozen=True, slots=True)
class SMSTemplate:
	id: str
	body: str
	variables: frozenset[str]
	transactional: bool


class SMSProvider(Protocol):
	def verify_and_parse_inbound(self, raw_body: bytes, headers: dict[str, str], secret: str) -> InboundSMS:
		...

	def verify_and_parse_delivery(
		self, raw_body: bytes, headers: dict[str, str], secret: str
	) -> SMSDeliveryEvent:
		...

	def send(self, sms: OutboundSMS) -> SMSSendResult:
		...

	def poll(self, cursor: str | None, limit: int) -> tuple[list[InboundSMS], str | None]:
		...


class SMSEntityResolver(Protocol):
	def resolve(self, company: str, sender_number: str) -> EntityLinks:
		...


class FrappeSMSProvider:
	def verify_and_parse_inbound(self, raw_body, headers, secret):
		self._verify(raw_body, headers, secret)
		payload = json.loads(raw_body)
		return InboundSMS(
			str(payload["id"]),
			str(payload["from"]),
			str(payload["to"]),
			str(payload.get("body") or ""),
			datetime.fromisoformat(payload["received_at"]),
			str(payload["thread_id"]) if payload.get("thread_id") else None,
			payload.get("metadata") or {},
		)

	def verify_and_parse_delivery(self, raw_body, headers, secret):
		self._verify(raw_body, headers, secret)
		payload = json.loads(raw_body)
		state = DeliveryState(str(payload["state"]).lower())
		if state not in {DeliveryState.SENT, DeliveryState.DELIVERED, DeliveryState.FAILED}:
			raise ValueError("Unsupported SMS delivery state")
		return SMSDeliveryEvent(
			str(payload["id"]),
			state,
			datetime.fromisoformat(payload["occurred_at"]),
			payload.get("error"),
			payload.get("metadata") or {},
		)

	def send(self, sms):
		from frappe.core.doctype.sms_settings.sms_settings import send_sms

		send_sms([sms.to_number], sms.body)
		key = hashlib.sha256(sms.idempotency_key.encode()).hexdigest()[:24]
		return SMSSendResult(
			f"frappe:{sms.reference_id}:{key}",
			DeliveryState.SENT,
			datetime.now(UTC),
		)

	def poll(self, cursor, limit):
		return [], cursor

	@staticmethod
	def _verify(raw_body: bytes, headers: dict[str, str], secret: str) -> None:
		provided = headers.get("X-Field-OS-Signature") or headers.get("x-field-os-signature") or ""
		expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
		if not secret or not hmac.compare_digest(provided.removeprefix("sha256="), expected):
			raise PermissionError("Invalid SMS webhook signature")


def render_sms_template(template: SMSTemplate, variables: dict[str, str]) -> str:
	if set(variables) != set(template.variables):
		missing = template.variables - variables.keys()
		extra = variables.keys() - template.variables
		details = []
		if missing:
			details.append(f"missing: {', '.join(sorted(missing))}")
		if extra:
			details.append(f"unexpected: {', '.join(sorted(extra))}")
		raise ValueError(f"Invalid SMS template variables ({'; '.join(details)})")
	return _TEMPLATE_TOKEN.sub(lambda match: str(variables[match.group(1)]), template.body)


class SMSService:
	def __init__(
		self,
		repository: CommunicationRepository,
		classifier: EmailClassifier,
		resolver: SMSEntityResolver,
		proposals: ProposalStore | None = None,
	) -> None:
		self.repository = repository
		self.communications = CommunicationService(repository)
		self.classifier = classifier
		self.resolver = resolver
		self.proposals = proposals

	def receive(self, company: str, integration_id: str, sms: InboundSMS) -> SMSReceiveResult:
		from_number = normalize_address(CommunicationChannel.SMS, sms.from_number)
		previous = self.repository.find_message_by_dedupe(company, f"{integration_id}:{sms.external_id}")
		if previous:
			return SMSReceiveResult(
				IngestResult(self.repository.get_thread(company, previous.thread_id), previous, False)
			)
		consent_state = self._apply_keyword(company, from_number, sms.body, sms.received_at)
		if (
			consent_state is None
			and self.repository.get_preference(company, CommunicationChannel.SMS, from_number) is None
		):
			self.repository.save_preference(
				ContactPreference(
					company,
					from_number,
					CommunicationChannel.SMS,
					ConsentState.TRANSACTIONAL_ONLY,
					"inbound_conversation",
					sms.received_at,
				)
			)
		links = self.resolver.resolve(company, from_number)
		classification = (
			EmailClassification("consent", "normal", 1.0)
			if consent_state
			else self.classifier.classify("SMS", sms.body)
		)
		sender = CommunicationParticipant(
			from_number,
			ParticipantRole.CUSTOMER if links.customer_id else ParticipantRole.EXTERNAL,
		)
		recipient = CommunicationParticipant(
			normalize_address(CommunicationChannel.SMS, sms.to_number), ParticipantRole.USER
		)
		thread = CommunicationThread(
			None,
			company,
			f"SMS with {from_number}",
			CommunicationChannel.SMS,
			ThreadState.OPEN,
			(sender, recipient),
			links,
			classification=classification.category,
			sla_due_at=sms.received_at
			+ timedelta(minutes={"urgent": 15, "high": 60, "normal": 240}.get(classification.priority, 240)),
			external_thread_id=f"{integration_id}:{sms.external_thread_id or from_number}",
		)
		message = CommunicationMessage(
			None,
			company,
			None,
			CommunicationChannel.SMS,
			MessageDirection.INBOUND,
			sender,
			(recipient,),
			sms.body,
			sms.received_at,
			DeliveryState.RECEIVED,
			external_id=sms.external_id,
			dedupe_key=f"{integration_id}:{sms.external_id}",
			provider=integration_id,
			classification=classification.category,
			metadata=sms.metadata or {},
		)
		return SMSReceiveResult(self.communications.ingest(thread, message), consent_state)

	def draft(
		self,
		context: TenantContext,
		thread_id: str,
		integration_id: str,
		from_number: str,
		to_number: str,
		body: str,
		*,
		transactional: bool,
	) -> CommunicationMessage:
		to_number = normalize_address(CommunicationChannel.SMS, to_number)
		if not re.fullmatch(r"\+[1-9][0-9]{7,14}", to_number):
			raise ValueError("Outbound SMS recipient must be an E.164 number")
		body = body.strip()
		if not body or len(body) > 1600:
			raise ValueError("SMS body must contain 1 to 1,600 characters")
		if not self.communications.can_send(
			context.company, to_number, CommunicationChannel.SMS, transactional=transactional
		):
			raise PermissionError("SMS consent does not allow this message")
		message = CommunicationMessage(
			None,
			context.company,
			thread_id,
			CommunicationChannel.SMS,
			MessageDirection.OUTBOUND,
			CommunicationParticipant(
				normalize_address(CommunicationChannel.SMS, from_number), ParticipantRole.USER, context.user
			),
			(CommunicationParticipant(to_number, ParticipantRole.CUSTOMER),),
			body,
			datetime.now(UTC),
			DeliveryState.DRAFT,
			provider=integration_id,
			metadata={"transactional": transactional},
		)
		return self.communications.create_draft(context, message)

	def preview_send(self, context: TenantContext, message_id: str) -> ActionProposal:
		authorize(context, "communicate")
		message = self.repository.get_message(context.company, message_id)
		if message is None or message.channel != CommunicationChannel.SMS:
			raise ValueError("SMS draft was not found")
		if message.delivery_state not in {DeliveryState.DRAFT, DeliveryState.FAILED}:
			raise ValueError("Only draft or failed SMS can be sent")
		if not self.communications.can_send(
			context.company,
			message.recipients[0].address,
			CommunicationChannel.SMS,
			transactional=bool(message.metadata.get("transactional")),
		):
			raise PermissionError("SMS consent changed; sending is blocked")
		now = datetime.now(UTC)
		proposal = ActionProposal(
			str(uuid4()),
			"send_sms",
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
		provider: SMSProvider,
		integration_id: str,
		from_number: str,
		engine: ActionEngine,
	) -> ExecutionReceipt:
		authorize(context, "communicate")
		if not self.proposals:
			raise ValueError("Proposal storage is not configured")
		proposal = self.proposals.load(context.company, proposal_id)
		proposal = require_proposal(proposal, context, tool="send_sms", risk=RiskClass.EXTERNAL)
		message = self.repository.get_message(context.company, str(proposal.arguments["message_id"]))
		if message is None or message.delivery_state != DeliveryState.PENDING_APPROVAL:
			raise ValueError("SMS is no longer pending approval")
		if proposal.arguments.get("message_digest") != message_digest(message):
			raise ValueError("Message changed after preview; generate a new approval")
		if message.sender.address != from_number:
			raise ValueError("Sender changed after preview; generate a new approval")
		if message.provider != integration_id:
			raise PermissionError("SMS integration does not match the approved draft")
		if not self.communications.can_send(
			context.company,
			message.recipients[0].address,
			CommunicationChannel.SMS,
			transactional=bool(message.metadata.get("transactional")),
		):
			raise PermissionError("SMS consent changed; sending is blocked")

		def execute():
			queued = self.repository.save_message(
				replace(message, delivery_state=DeliveryState.QUEUED, error=None)
			)
			try:
				result = provider.send(
					OutboundSMS(
						from_number,
						queued.recipients[0].address,
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
					metadata={**queued.metadata, **(result.metadata or {})},
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
		self, company: str, integration_id: str, event: SMSDeliveryEvent
	) -> CommunicationMessage:
		message = self.repository.find_message_by_external_id(
			company, CommunicationChannel.SMS, event.external_id, integration_id
		)
		if message is None:
			raise ValueError("Delivery event references an unknown SMS")
		if not accept_delivery(message, event):
			return message
		return self.repository.save_message(
			replace(
				message,
				delivery_state=event.state,
				error=event.error,
				metadata={
					**message.metadata,
					**(event.metadata or {}),
					"delivery_event_at": event.occurred_at.isoformat(),
				},
			)
		)

	def _apply_keyword(
		self, company: str, address: str, body: str, occurred_at: datetime
	) -> ConsentState | None:
		keyword = body.strip().upper()
		state = (
			ConsentState.OPTED_OUT
			if keyword in STOP_WORDS
			else ConsentState.OPTED_IN
			if keyword in START_WORDS
			else None
		)
		if state:
			previous = self.repository.get_preference(company, CommunicationChannel.SMS, address)
			if previous and (
				timestamp(previous.updated_at) > timestamp(occurred_at)
				or (
					timestamp(previous.updated_at) == timestamp(occurred_at)
					and state != ConsentState.OPTED_OUT
				)
			):
				return previous.state
			self.repository.save_preference(
				ContactPreference(
					company, address, CommunicationChannel.SMS, state, "inbound_keyword", occurred_at, keyword
				)
			)
		return state
