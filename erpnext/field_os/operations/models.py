"""Stable read models used by the operator API and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class AttentionSeverity(StrEnum):
	CRITICAL = "critical"
	WARNING = "warning"
	INFO = "info"


@dataclass(frozen=True, slots=True)
class RecordLink:
	doctype: str
	record_id: str
	label: str


@dataclass(frozen=True, slots=True)
class AttentionItem:
	id: str
	kind: str
	severity: AttentionSeverity
	title: str
	summary: str
	record: RecordLink
	due_at: datetime | None = None
	owner: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TodaySnapshot:
	company: str
	day: date
	counts: dict[str, int]
	attention: tuple[AttentionItem, ...]


@dataclass(frozen=True, slots=True)
class SearchResult:
	id: str
	kind: str
	title: str
	subtitle: str
	record: RecordLink
