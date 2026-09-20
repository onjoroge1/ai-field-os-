from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.ai.conversation import ProposalStore
from erpnext.field_os.security.authorization import authorize


@dataclass(frozen=True, slots=True)
class Line:
	item_code: str
	quantity: Decimal
	rate: Decimal
	kind: str


@dataclass(frozen=True, slots=True)
class Completion:
	id: str
	company: str
	customer_id: str
	status: str
	checks: tuple[bool, ...]
	signature: str | None
	photos: tuple[str, ...]
	lines: tuple[Line, ...]
	version: str | None = None

	@property
	def total(self):
		return sum((x.quantity * x.rate for x in self.lines), Decimal(0))


class Repo(Protocol):
	def get(self, company: str, completion_id: str) -> Completion:
		...

	def complete(self, company: str, completion_id: str, user: str, version: str | None) -> Completion:
		...

	def invoice(self, company: str, completion_id: str, due: date, version: str | None) -> str:
		...


class CompletionService:
	def __init__(self, repo: Repo, proposals: ProposalStore):
		self.repo, self.proposals = repo, proposals

	def complete(self, context, completion_id, version):
		authorize(context, "field_update")
		item = self.repo.get(context.company, completion_id)
		if not item.checks or not all(item.checks) or not item.signature or not item.photos or not item.lines:
			raise ValueError("Checklist, signature, photos, and billables are required")
		return self.repo.complete(context.company, completion_id, context.user, version)

	def preview_invoice(self, context, completion_id, due):
		authorize(context, "invoice")
		item = self.repo.get(context.company, completion_id)
		if item.status != "Completed":
			raise ValueError("Completion is not invoice-ready")
		now = datetime.now(UTC)
		p = ActionProposal(
			str(uuid4()),
			"create_invoice",
			{"completion_id": item.id, "due": due.isoformat(), "version": item.version},
			RiskClass.FINANCIAL,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=10),
		)
		self.proposals.save(p)
		return p, item.total

	def commit_invoice(self, context, proposal_id, key, engine: ActionEngine):
		p = self.proposals.load(context.company, proposal_id)
		if not p or p.actor != context.user:
			raise ValueError("Proposal missing")
		return engine.execute(
			p,
			key,
			lambda: {
				"invoice_id": self.repo.invoice(
					context.company,
					p.arguments["completion_id"],
					date.fromisoformat(p.arguments["due"]),
					p.arguments.get("version"),
				)
			},
			approved_by=context.user,
		)
