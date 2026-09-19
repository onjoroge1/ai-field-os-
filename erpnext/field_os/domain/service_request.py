"""Service request lifecycle independent of ERP persistence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class RequestStatus(StrEnum):
	NEW = "new"
	TRIAGED = "triaged"
	PROPOSED = "proposed"
	BOOKED = "booked"
	CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ServiceRequest:
	id: str
	company: str
	customer_id: str
	site_id: str
	summary: str
	status: RequestStatus = RequestStatus.NEW
	equipment_id: str | None = None
	requested_start: datetime | None = None
	requested_end: datetime | None = None

	def transition(self, target: RequestStatus) -> ServiceRequest:
		allowed = {
			RequestStatus.NEW: {RequestStatus.TRIAGED, RequestStatus.CANCELLED},
			RequestStatus.TRIAGED: {RequestStatus.PROPOSED, RequestStatus.CANCELLED},
			RequestStatus.PROPOSED: {RequestStatus.BOOKED, RequestStatus.TRIAGED, RequestStatus.CANCELLED},
			RequestStatus.BOOKED: {RequestStatus.CANCELLED},
			RequestStatus.CANCELLED: set(),
		}
		if target not in allowed[self.status]:
			raise ValueError(f"Invalid service request transition: {self.status} -> {target}")
		return replace(self, status=target)
