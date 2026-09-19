"""Deterministic scheduling primitives. AI does not decide schedule validity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Technician:
	id: str
	name: str
	skills: frozenset[str]


@dataclass(frozen=True, slots=True)
class BusyWindow:
	technician_id: str
	start: datetime
	end: datetime


@dataclass(frozen=True, slots=True)
class ScheduleRequest:
	start: datetime
	end: datetime
	required_skills: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ScheduleProposal:
	technician_id: str
	start: datetime
	end: datetime


def _overlaps(start: datetime, end: datetime, busy: BusyWindow) -> bool:
	return start < busy.end and end > busy.start


def propose_technicians(
	request: ScheduleRequest,
	technicians: list[Technician],
	busy_windows: list[BusyWindow],
) -> list[ScheduleProposal]:
	if request.end <= request.start:
		raise ValueError("Schedule end must be after start")

	proposals: list[ScheduleProposal] = []
	for technician in sorted(technicians, key=lambda item: item.id):
		if not request.required_skills.issubset(technician.skills):
			continue
		if any(
			window.technician_id == technician.id and _overlaps(request.start, request.end, window)
			for window in busy_windows
		):
			continue
		proposals.append(ScheduleProposal(technician.id, request.start, request.end))
	return proposals
