from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from erpnext.field_os.actions.models import ActionProposal


@dataclass(frozen=True, slots=True)
class DispatchJob:
	id: str
	company: str
	customer_id: str
	customer_name: str
	site_id: str | None
	summary: str
	status: str
	start: datetime
	end: datetime
	technician_id: str | None = None
	technician_name: str | None = None
	technician_user: str | None = None
	version: str | None = None


@dataclass(frozen=True, slots=True)
class TechnicianStatus:
	id: str
	name: str
	status: str
	user: str | None = None
	current_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchConflict:
	technician_id: str
	job_ids: tuple[str, str]
	start: datetime
	end: datetime


@dataclass(frozen=True, slots=True)
class DispatchBoard:
	start: datetime
	end: datetime
	jobs: tuple[DispatchJob, ...]
	technicians: tuple[TechnicianStatus, ...]
	conflicts: tuple[DispatchConflict, ...]


@dataclass(frozen=True, slots=True)
class DispatchChangePreview:
	proposal: ActionProposal
	job: DispatchJob
	conflicts: tuple[DispatchConflict, ...]
	can_commit: bool
