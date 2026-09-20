from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.actions.validation import require_proposal
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
		if item.company != context.company or item.id != completion_id:
			raise ValueError("Completion is outside this tenant")
		if item.status != "Draft" or not version or item.version != version:
			raise ValueError("Completion changed; reload before completing")
		self._validate_evidence(item)
		return self.repo.complete(context.company, completion_id, context.user, version)

	@staticmethod
	def _validate_evidence(item):
		if (
			not item.checks
			or any(check is not True for check in item.checks)
			or not item.signature
			or not item.photos
			or not item.lines
		):
			raise ValueError("Checklist, signature, photos, and billables are required")
		for line in item.lines:
			if (
				not line.item_code
				or line.kind not in {"Labor", "Part"}
				or not line.quantity.is_finite()
				or not line.rate.is_finite()
				or line.quantity <= 0
				or line.rate < 0
			):
				raise ValueError("Billable lines require finite positive quantities and nonnegative rates")

	def preview_invoice(self, context, completion_id, due):
		authorize(context, "invoice")
		item = self.repo.get(context.company, completion_id)
		if item.company != context.company or item.id != completion_id:
			raise ValueError("Completion is outside this tenant")
		if item.status != "Completed" or not item.version:
			raise ValueError("Completion is not invoice-ready")
		self._validate_evidence(item)
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
		authorize(context, "invoice")
		p = require_proposal(
			self.proposals.load(context.company, proposal_id),
			context,
			tool="create_invoice",
			risk=RiskClass.FINANCIAL,
		)

		def execute():
			item = self.repo.get(context.company, p.arguments["completion_id"])
			if (
				item.company != context.company
				or item.id != p.arguments["completion_id"]
				or item.status != "Completed"
				or not item.version
				or item.version != p.arguments.get("version")
			):
				raise ValueError("Completion changed; regenerate the invoice preview")
			self._validate_evidence(item)
			return {
				"invoice_id": self.repo.invoice(
					context.company, item.id, date.fromisoformat(p.arguments["due"]), item.version
				)
			}

		return engine.execute(
			p,
			key,
			execute,
			approved_by=context.user,
		)
