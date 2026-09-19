"""Deterministic dispatch board and reschedule/reassign workflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt, RiskClass
from erpnext.field_os.ai.conversation import ProposalStore
from erpnext.field_os.dispatch.models import (
	DispatchBoard,
	DispatchChangePreview,
	DispatchConflict,
	DispatchJob,
	TechnicianStatus,
)
from erpnext.field_os.dispatch.repository import DispatchRepository
from erpnext.field_os.security.authorization import CapabilityDenied, authorize, capabilities_for
from erpnext.field_os.security.context import TenantContext


def _overlap(left: DispatchJob, right: DispatchJob) -> bool:
	return left.start < right.end and left.end > right.start


class DispatchService:
	def __init__(self, repository: DispatchRepository, proposals: ProposalStore | None = None) -> None:
		self.repository = repository
		self.proposals = proposals

	def board(self, context: TenantContext, start: datetime, end: datetime) -> DispatchBoard:
		if end <= start:
			raise ValueError("Dispatch range end must be after start")
		capabilities = capabilities_for(context)
		if "dispatch" not in capabilities and "field_update" not in capabilities:
			raise CapabilityDenied("Dispatch or field update access is required")
		jobs = self.repository.list_jobs(context.company, start, end)
		technicians = self.repository.list_technicians(context.company)
		if "dispatch" not in capabilities:
			jobs = [job for job in jobs if job.technician_user == context.user]
			technicians = [technician for technician in technicians if technician.user == context.user]
		now = datetime.now(UTC)
		technicians = [self._with_live_status(technician, jobs, now) for technician in technicians]
		conflicts = self._conflicts(jobs)
		return DispatchBoard(start, end, tuple(jobs), tuple(technicians), conflicts)

	@staticmethod
	def _with_live_status(
		technician: TechnicianStatus,
		jobs: list[DispatchJob],
		now: datetime,
	) -> TechnicianStatus:
		active = next(
			(job for job in jobs if job.technician_id == technician.id and job.start <= now < job.end),
			None,
		)
		return TechnicianStatus(
			technician.id,
			technician.name,
			"busy" if active else technician.status,
			technician.user,
			active.id if active else None,
		)

	def preview_change(
		self,
		context: TenantContext,
		job_id: str,
		technician_id: str,
		start: datetime,
		end: datetime,
		expected_version: str | None,
	) -> DispatchChangePreview:
		authorize(context, "dispatch")
		if end <= start:
			raise ValueError("Job end must be after start")
		job = self.repository.get_job(context.company, job_id)
		candidate = DispatchJob(
			job.id,
			job.company,
			job.customer_id,
			job.customer_name,
			job.site_id,
			job.summary,
			job.status,
			start,
			end,
			technician_id,
			version=job.version,
		)
		window_start = start - timedelta(days=1)
		window_end = end + timedelta(days=1)
		others = [
			item
			for item in self.repository.list_jobs(context.company, window_start, window_end)
			if item.id != job.id
		]
		conflicts = self._conflicts([candidate, *others], only_job_id=job.id)
		now = datetime.now(UTC)
		proposal = ActionProposal(
			id=str(uuid4()),
			tool="change_dispatch_assignment",
			arguments={
				"job_id": job.id,
				"technician_id": technician_id,
				"start": start.isoformat(),
				"end": end.isoformat(),
				"expected_version": expected_version,
			},
			risk=RiskClass.LOW,
			company=context.company,
			actor=context.user,
			created_at=now,
			expires_at=now + timedelta(minutes=10),
		)
		if self.proposals:
			self.proposals.save(proposal)
		return DispatchChangePreview(proposal, candidate, conflicts, not conflicts)

	def commit_change(
		self,
		context: TenantContext,
		proposal_id: str,
		idempotency_key: str,
		engine: ActionEngine,
	) -> ExecutionReceipt:
		authorize(context, "dispatch")
		if not self.proposals:
			raise ValueError("Proposal storage is not configured")
		proposal = self.proposals.load(context.company, proposal_id)
		if proposal is None or proposal.tool != "change_dispatch_assignment":
			raise ValueError("Dispatch proposal is missing or expired")
		args = proposal.arguments
		candidate_start = datetime.fromisoformat(str(args["start"]))
		candidate_end = datetime.fromisoformat(str(args["end"]))
		current = self.repository.get_job(context.company, str(args["job_id"]))
		candidate = DispatchJob(
			current.id,
			current.company,
			current.customer_id,
			current.customer_name,
			current.site_id,
			current.summary,
			current.status,
			candidate_start,
			candidate_end,
			str(args["technician_id"]),
			version=current.version,
		)
		others = [
			item
			for item in self.repository.list_jobs(
				context.company, candidate_start - timedelta(days=1), candidate_end + timedelta(days=1)
			)
			if item.id != candidate.id
		]
		if self._conflicts([candidate, *others], only_job_id=candidate.id):
			raise ValueError("Schedule now conflicts with another job; refresh and retry")

		def execute():
			job = self.repository.update_assignment(
				context.company,
				str(args["job_id"]),
				str(args["technician_id"]),
				candidate_start,
				candidate_end,
				args.get("expected_version"),
			)
			return {"job_id": job.id, "technician_id": job.technician_id, "start": job.start.isoformat()}

		receipt = engine.execute(proposal, idempotency_key, execute, approved_by=context.user)
		self.proposals.delete(context.company, proposal_id)
		return receipt

	@staticmethod
	def _conflicts(jobs: list[DispatchJob], only_job_id: str | None = None) -> tuple[DispatchConflict, ...]:
		conflicts = []
		ordered = sorted(
			(job for job in jobs if job.technician_id),
			key=lambda item: (item.technician_id, item.start, item.id),
		)
		for index, left in enumerate(ordered):
			for right in ordered[index + 1 :]:
				if right.technician_id != left.technician_id:
					break
				if _overlap(left, right) and (only_job_id is None or only_job_id in {left.id, right.id}):
					conflicts.append(
						DispatchConflict(
							left.technician_id or "",
							(left.id, right.id),
							max(left.start, right.start),
							min(left.end, right.end),
						)
					)
		return tuple(conflicts)
