from __future__ import annotations

from datetime import datetime
from typing import Protocol

from erpnext.field_os.dispatch.models import DispatchJob, TechnicianStatus


class DispatchRepository(Protocol):
	def list_jobs(self, company: str, start: datetime, end: datetime) -> list[DispatchJob]:
		...

	def list_technicians(self, company: str) -> list[TechnicianStatus]:
		...

	def get_job(self, company: str, job_id: str) -> DispatchJob:
		...

	def update_assignment(
		self,
		company: str,
		job_id: str,
		technician_id: str,
		start: datetime,
		end: datetime,
		expected_version: str | None,
	) -> DispatchJob:
		...
