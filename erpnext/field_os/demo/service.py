from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, RiskClass
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
		return self.repo.seed(context.company)

	def scenarios(self, context):
		authorize(context, "read")
		d = self.repo.get(context.company)
		return (
			SCENARIOS if d and d.status == "Ready" else (_ for _ in ()).throw(ValueError("Demo not seeded"))
		)

	def preview_reset(self, context):
		authorize(context, "admin")
		d = self.repo.get(context.company)
		if not d or d.status != "Ready":
			raise ValueError("Demo not ready")
		now = datetime.now(UTC)
		p = ActionProposal(
			str(uuid4()),
			"reset_demo",
			{"seed_version": d.seed_version, "record_count": len(d.records)},
			RiskClass.DESTRUCTIVE,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=10),
		)
		self.proposals.save(p)
		return p

	def reset(self, context, pid, key, engine: ActionEngine):
		p = self.proposals.load(context.company, pid)
		d = self.repo.get(context.company)
		if d.seed_version != p.arguments["seed_version"]:
			raise ValueError("Demo changed")
		return engine.execute(p, key, lambda: self.repo.reset(context.company), approved_by=context.user)
