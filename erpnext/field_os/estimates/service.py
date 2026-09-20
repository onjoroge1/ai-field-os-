from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.ai.conversation import ProposalStore
from erpnext.field_os.estimates.models import Estimate, EstimateLine
from erpnext.field_os.security.authorization import authorize


class EstimateRepository(Protocol):
	def get(self, company: str, estimate_id: str) -> Estimate:
		...

	def stock(self, company: str, item_code: str, warehouse: str | None):
		...

	def set_status(self, company: str, estimate_id: str, status: str, version: str | None) -> Estimate:
		...


class EstimateService:
	def __init__(self, repository: EstimateRepository, proposals: ProposalStore):
		self.repository, self.proposals = repository, proposals

	def preview_send(self, context, estimate_id):
		authorize(context, "quote")
		estimate = self.repository.get(context.company, estimate_id)
		if estimate.status not in {"Draft", "Revised"}:
			raise ValueError("Estimate cannot be sent")
		lines = tuple(
			EstimateLine(
				x.item_code,
				x.description,
				x.quantity,
				x.rate,
				x.warehouse,
				self.repository.stock(context.company, x.item_code, x.warehouse),
			)
			for x in estimate.lines
		)
		now = datetime.now(UTC)
		proposal = ActionProposal(
			str(uuid4()),
			"send_estimate",
			{"estimate_id": estimate.id, "expected_version": estimate.version},
			RiskClass.EXTERNAL,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=10),
		)
		self.proposals.save(proposal)
		return proposal, tuple(x for x in lines if x.available_quantity < x.quantity)

	def commit_send(self, context, proposal_id, key, engine: ActionEngine):
		proposal = self.proposals.load(context.company, proposal_id)
		if not proposal or proposal.tool != "send_estimate" or proposal.actor != context.user:
			raise ValueError("Proposal missing")
		return engine.execute(
			proposal,
			key,
			lambda: self.repository.set_status(
				context.company,
				proposal.arguments["estimate_id"],
				"Sent",
				proposal.arguments.get("expected_version"),
			),
			approved_by=context.user,
		)

	def customer_decision(self, context, estimate_id, decision):
		authorize(context, "quote")
		estimate = self.repository.get(context.company, estimate_id)
		if estimate.status != "Sent" or decision not in {"Approved", "Rejected"}:
			raise ValueError("Invalid decision")
		return self.repository.set_status(context.company, estimate_id, decision, estimate.version)
