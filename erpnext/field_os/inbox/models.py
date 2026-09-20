from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from erpnext.field_os.communications.models import CommunicationMessage, CommunicationThread


class SLAState(StrEnum):
	OVERDUE = "overdue"
	DUE_SOON = "due_soon"
	ON_TRACK = "on_track"
	NONE = "none"


@dataclass(frozen=True, slots=True)
class SuggestedAction:
	id: str
	label: str
	kind: str
	arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class InboxItem:
	thread: CommunicationThread
	latest_message: CommunicationMessage | None
	age_seconds: int
	sla_state: SLAState
	suggestions: tuple[SuggestedAction, ...]


@dataclass(frozen=True, slots=True)
class InboxQueue:
	items: tuple[InboxItem, ...]
	counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class InboxDetail:
	thread: CommunicationThread
	messages: tuple[CommunicationMessage, ...]
	suggestions: tuple[SuggestedAction, ...]


@dataclass(frozen=True, slots=True)
class CorrectionFeedback:
	company: str
	thread_id: str
	field: str
	previous_value: str | None
	corrected_value: str
	actor: str
	occurred_at: datetime
	reason: str | None = None
	message_id: str | None = None
