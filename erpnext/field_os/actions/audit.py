"""Append-only audit event shape. Persistence arrives with production event storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class AuditEvent:
	event: str
	company: str
	actor: str
	proposal_id: str
	occurred_at: datetime
	details: dict[str, Any]
