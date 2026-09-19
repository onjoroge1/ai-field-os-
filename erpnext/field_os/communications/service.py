"""Channel-neutral communication ingestion and linking."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationMessage,
	CommunicationThread,
	ConsentState,
	ContactPreference,
	DeliveryState,
	IngestResult,
	MessageDirection,
	ThreadState,
)
from erpnext.field_os.communications.repository import CommunicationRepository
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


def normalize_address(channel: CommunicationChannel, address: str) -> str:
	value = address.strip()
	if channel == CommunicationChannel.EMAIL:
		return value.lower()
	if channel == CommunicationChannel.SMS:
		prefix = "+" if value.startswith("+") else ""
		digits = "".join(character for character in value if character.isdigit())
		return f"{prefix}{digits}"
	return value


class CommunicationService:
	def __init__(self, repository: CommunicationRepository) -> None:
		self.repository = repository

	def ingest(
		self,
		thread: CommunicationThread,
		message: CommunicationMessage,
	) -> IngestResult:
		if message.company != thread.company:
			raise PermissionError("Message and thread tenants do not match")
		if message.direction != MessageDirection.INBOUND:
			raise ValueError("Ingestion accepts inbound messages only")
		if message.delivery_state != DeliveryState.RECEIVED:
			raise ValueError("Inbound messages must enter as received")
		if not message.dedupe_key:
			raise ValueError("Inbound message dedupe_key is required")
		existing = self.repository.find_message_by_dedupe(message.company, message.dedupe_key)
		if existing:
			existing_thread = self.repository.get_thread(message.company, existing.thread_id or "")
			if existing_thread is None:
				raise RuntimeError("Deduplicated message references a missing thread")
			return IngestResult(existing_thread, existing, False)

		persisted_thread = self._resolve_thread(thread)
		persisted_message = self.repository.save_message(replace(message, thread_id=persisted_thread.id))
		updated_thread = replace(
			persisted_thread,
			last_message_at=max(
				(
					value
					for value in (persisted_thread.last_message_at, persisted_message.occurred_at)
					if value
				),
			),
		)
		updated_thread = self.repository.save_thread(updated_thread)
		return IngestResult(updated_thread, persisted_message, True)

	def create_draft(
		self,
		context: TenantContext,
		message: CommunicationMessage,
	) -> CommunicationMessage:
		authorize(context, "communicate")
		if message.company != context.company:
			raise PermissionError("Cross-tenant draft rejected")
		if message.direction != MessageDirection.OUTBOUND or message.delivery_state != DeliveryState.DRAFT:
			raise ValueError("Outbound drafts must start in draft state")
		thread = self.repository.get_thread(context.company, message.thread_id or "")
		if thread is None:
			raise ValueError("Draft thread was not found")
		return self.repository.save_message(message)

	def set_preference(
		self,
		context: TenantContext,
		address: str,
		channel: CommunicationChannel,
		state: ConsentState,
		source: str,
		proof: str | None = None,
	) -> ContactPreference:
		authorize(context, "communicate")
		preference = ContactPreference(
			context.company,
			normalize_address(channel, address),
			channel,
			state,
			source,
			datetime.now(UTC),
			proof,
		)
		return self.repository.save_preference(preference)

	def can_send(
		self,
		company: str,
		address: str,
		channel: CommunicationChannel,
		*,
		transactional: bool,
	) -> bool:
		preference = self.repository.get_preference(company, channel, normalize_address(channel, address))
		if preference and preference.state == ConsentState.OPTED_OUT:
			return False
		if preference and preference.state == ConsentState.TRANSACTIONAL_ONLY:
			return transactional
		if channel == CommunicationChannel.SMS and not transactional:
			return bool(preference and preference.state == ConsentState.OPTED_IN)
		return True

	def _resolve_thread(self, proposed: CommunicationThread) -> CommunicationThread:
		if proposed.id:
			existing = self.repository.get_thread(proposed.company, proposed.id)
			if existing is None:
				raise ValueError("Thread was not found in tenant")
			return existing
		if proposed.external_thread_id:
			existing = self.repository.find_thread_by_external_id(
				proposed.company, proposed.channel, proposed.external_thread_id
			)
			if existing:
				return existing
		if proposed.state not in {ThreadState.OPEN, ThreadState.PENDING}:
			raise ValueError("New inbound threads must start open or pending")
		return self.repository.save_thread(proposed)
