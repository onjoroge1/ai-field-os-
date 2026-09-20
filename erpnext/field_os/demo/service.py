from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.actions.validation import require_proposal
from erpnext.field_os.ai.conversation import ProposalStore
from erpnext.field_os.security.authorization import authorize


@dataclass(frozen=True, slots=True)
class Demo:
	company: str
	status: str
	seed_version: str
	records: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Scenario:
	id: str
	title: str
	steps: tuple[str, ...]


SCENARIOS = (
	Scenario(
		"urgent-no-cooling",
		"Urgent no-cooling request",
		("Triage Inbox", "Book visit", "Dispatch technician"),
	),
	Scenario(
		"maintenance-renewal",
		"Preventive maintenance renewal",
		("Review due visit", "Schedule", "Approve renewal"),
	),
	Scenario(
		"estimate-to-invoice",
		"Estimate through invoice",
		("Build estimate", "Record approval", "Complete and invoice"),
	),
)


class Repo(Protocol):
	def get(self, company: str) -> Demo | None:
		...

	def seed(self, company: str) -> Demo:
		...

	def reset(self, company: str) -> Demo:
		...


class DemoService:
	def __init__(self, repo: Repo, proposals: ProposalStore):
		self.repo, self.proposals = repo, proposals

	def seed(self, context):
		authorize(context, "admin")
		existing = self.repo.get(context.company)
		if existing:
			if existing.company != context.company or existing.status != "Ready":
				raise ValueError("Demo is not ready for reuse")
			return existing
		return self.repo.seed(context.company)

	def scenarios(self, context):
		authorize(context, "read")
		d = self.repo.get(context.company)
		if not d or d.company != context.company or d.status != "Ready":
			raise ValueError("Demo not seeded")
		return SCENARIOS

	def preview_reset(self, context):
		authorize(context, "admin")
		d = self.repo.get(context.company)
		if not d or d.company != context.company or d.status != "Ready" or not d.seed_version:
			raise ValueError("Demo not ready")
		now = datetime.now(UTC)
		p = ActionProposal(
			str(uuid4()),
			"reset_demo",
			{
				"seed_version": d.seed_version,
				"record_count": len(d.records),
				"records": [list(record) for record in d.records],
			},
			RiskClass.DESTRUCTIVE,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=10),
		)
		self.proposals.save(p)
		return p

	def reset(self, context, pid, key, engine: ActionEngine):
		authorize(context, "admin")
		p = require_proposal(
			self.proposals.load(context.company, pid),
			context,
			tool="reset_demo",
			risk=RiskClass.DESTRUCTIVE,
		)

		def execute():
			d = self.repo.get(context.company)
			if (
				not d
				or d.company != context.company
				or d.status != "Ready"
				or not d.seed_version
				or d.seed_version != p.arguments.get("seed_version")
				or [list(record) for record in d.records] != p.arguments.get("records")
			):
				raise ValueError("Demo changed; regenerate the reset preview")
			return self.repo.reset(context.company)

		return engine.execute(p, key, execute, approved_by=context.user)
