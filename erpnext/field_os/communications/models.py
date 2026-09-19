from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class CommunicationChannel(StrEnum):
	EMAIL = "email"
	SMS = "sms"
	WEB = "web"
	TECHNICIAN_NOTE = "technician_note"
	CALL = "call"


class MessageDirection(StrEnum):
	INBOUND = "inbound"
	OUTBOUND = "outbound"
	INTERNAL = "internal"


class DeliveryState(StrEnum):
	DRAFT = "draft"
	PENDING_APPROVAL = "pending_approval"
	QUEUED = "queued"
	SENT = "sent"
	DELIVERED = "delivered"
	FAILED = "failed"
	BOUNCED = "bounced"
	RECEIVED = "received"


class ThreadState(StrEnum):
	OPEN = "open"
	PENDING = "pending"
	CLOSED = "closed"
	SPAM = "spam"


class ParticipantRole(StrEnum):
	CUSTOMER = "customer"
	USER = "user"
	TECHNICIAN = "technician"
	EXTERNAL = "external"


class ConsentState(StrEnum):
	UNKNOWN = "unknown"
	OPTED_IN = "opted_in"
	OPTED_OUT = "opted_out"
	TRANSACTIONAL_ONLY = "transactional_only"


@dataclass(frozen=True, slots=True)
class EntityLinks:
	customer_id: str | None = None
	site_id: str | None = None
	equipment_id: str | None = None
	service_request_id: str | None = None
	job_id: str | None = None
	quote_id: str | None = None
	invoice_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommunicationParticipant:
	address: str
	role: ParticipantRole
	display_name: str | None = None
	contact_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommunicationAttachment:
	filename: str
	content_type: str
	size_bytes: int
	file_id: str | None = None
	external_url: str | None = None


@dataclass(frozen=True, slots=True)
class CommunicationThread:
	id: str | None
	company: str
	subject: str
	channel: CommunicationChannel
	state: ThreadState
	participants: tuple[CommunicationParticipant, ...]
	links: EntityLinks = field(default_factory=EntityLinks)
	assigned_to: str | None = None
	classification: str | None = None
	sla_due_at: datetime | None = None
	last_message_at: datetime | None = None
	external_thread_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommunicationMessage:
	id: str | None
	company: str
	thread_id: str | None
	channel: CommunicationChannel
	direction: MessageDirection
	sender: CommunicationParticipant
	recipients: tuple[CommunicationParticipant, ...]
	body: str
	occurred_at: datetime
	delivery_state: DeliveryState
	subject: str | None = None
	external_id: str | None = None
	dedupe_key: str | None = None
	provider: str | None = None
	attachments: tuple[CommunicationAttachment, ...] = ()
	classification: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)
	error: str | None = None


@dataclass(frozen=True, slots=True)
class ContactPreference:
	company: str
	address: str
	channel: CommunicationChannel
	state: ConsentState
	source: str
	updated_at: datetime
	proof: str | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
	thread: CommunicationThread
	message: CommunicationMessage
	created: bool
