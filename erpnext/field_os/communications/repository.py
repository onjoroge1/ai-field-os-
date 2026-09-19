from __future__ import annotations

from typing import Protocol

from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationMessage,
	CommunicationThread,
	ContactPreference,
)


class CommunicationRepository(Protocol):
	def get_thread(self, company: str, thread_id: str) -> CommunicationThread | None:
		...

	def find_thread_by_external_id(
		self, company: str, channel: CommunicationChannel, external_thread_id: str
	) -> CommunicationThread | None:
		...

	def save_thread(self, thread: CommunicationThread) -> CommunicationThread:
		...

	def list_threads(
		self,
		company: str,
		*,
		states: tuple[str, ...] = (),
		channel: CommunicationChannel | None = None,
		assigned_to: str | None = None,
		limit: int = 50,
	) -> list[CommunicationThread]:
		...

	def find_message_by_dedupe(self, company: str, dedupe_key: str) -> CommunicationMessage | None:
		...

	def get_message(self, company: str, message_id: str) -> CommunicationMessage | None:
		...

	def find_message_by_external_id(
		self,
		company: str,
		channel: CommunicationChannel,
		external_id: str,
		provider: str | None = None,
	) -> CommunicationMessage | None:
		...

	def save_message(self, message: CommunicationMessage) -> CommunicationMessage:
		...

	def list_messages(self, company: str, thread_id: str, limit: int = 100) -> list[CommunicationMessage]:
		...

	def get_preference(
		self, company: str, channel: CommunicationChannel, address: str
	) -> ContactPreference | None:
		...

	def save_preference(self, preference: ContactPreference) -> ContactPreference:
		...
