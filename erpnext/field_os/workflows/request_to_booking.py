"""First complete Field OS vertical slice: service request -> approved booking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt, RiskClass
from erpnext.field_os.domain.scheduling import BusyWindow, ScheduleProposal, ScheduleRequest, Technician, propose_technicians
from erpnext.field_os.domain.service_request import RequestStatus, ServiceRequest
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext


@dataclass(frozen=True, slots=True)
class BookingPlan:
	request: ServiceRequest
	schedule: ScheduleProposal
	proposal: ActionProposal
	customer_message: str


class RequestToBookingWorkflow:
	def plan(
		self,
		context: TenantContext,
		request: ServiceRequest,
		schedule_request: ScheduleRequest,
		technicians: list[Technician],
		busy_windows: list[BusyWindow],
	) -> BookingPlan:
		authorize(context, "dispatch")
		if request.company != context.company:
			raise PermissionError("Service request belongs to another tenant")

		triaged = request if request.status == RequestStatus.TRIAGED else request.transition(RequestStatus.TRIAGED)
		options = propose_technicians(schedule_request, technicians, busy_windows)
		if not options:
			raise ValueError("No eligible technician is available")

		proposed_request = triaged.transition(RequestStatus.PROPOSED)
		schedule = options[0]
		now = datetime.now(UTC)
		proposal = ActionProposal(
			id=str(uuid4()),
			tool="book_service_request",
			arguments={
				"request_id": request.id,
				"technician_id": schedule.technician_id,
				"start": schedule.start.isoformat(),
				"end": schedule.end.isoformat(),
			},
			risk=RiskClass.EXTERNAL,
			company=context.company,
			actor=context.user,
			created_at=now,
			expires_at=now + timedelta(minutes=10),
		)
		message = f"Your service visit is scheduled for {schedule.start.isoformat()}."
		return BookingPlan(proposed_request, schedule, proposal, message)

	def approve_and_book(
		self,
		context: TenantContext,
		plan: BookingPlan,
		approved_by: str,
		create_job: Callable[[BookingPlan], str],
		send_confirmation: Callable[[BookingPlan, str], None],
		action_engine: ActionEngine,
		idempotency_key: str,
	) -> ExecutionReceipt:
		authorize(context, "dispatch")
		if plan.proposal.company != context.company:
			raise PermissionError("Cross-tenant booking rejected")

		def execute() -> dict[str, str]:
			job_id = create_job(plan)
			send_confirmation(plan, job_id)
			return {"job_id": job_id, "request_status": RequestStatus.BOOKED.value}

		return action_engine.execute(
			plan.proposal,
			idempotency_key,
			execute,
			approved_by=approved_by,
		)
