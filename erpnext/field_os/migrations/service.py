import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.ai.conversation import ProposalStore
from erpnext.field_os.security.authorization import authorize

SCHEMAS = {
	"customers": (("customer_id", "customer_name", "email", "phone"), ("customer_id", "customer_name")),
	"sites": (
		("site_id", "customer_id", "title", "address_line1", "city", "state", "postal_code"),
		("site_id", "customer_id", "title", "address_line1"),
	),
	"equipment": (
		(
			"equipment_id",
			"customer_id",
			"site_id",
			"equipment_name",
			"unit_type",
			"model_number",
			"serial_number",
			"installed_on",
		),
		("equipment_id", "customer_id", "site_id", "equipment_name", "unit_type"),
	),
}


@dataclass(frozen=True, slots=True)
class Row:
	number: int
	data: dict[str, str]
	errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Batch:
	id: str
	company: str
	kind: str
	status: str
	rows: tuple[Row, ...]
	created: tuple[tuple[str, str], ...] = ()


class Repo(Protocol):
	def create(self, company: str, kind: str, rows: tuple[Row, ...], user: str) -> Batch:
		...

	def get(self, company: str, batch_id: str) -> Batch:
		...

	def apply(self, company: str, batch_id: str) -> Batch:
		...

	def rollback(self, company: str, batch_id: str) -> Batch:
		...


class MigrationService:
	def __init__(self, repo: Repo, proposals: ProposalStore):
		self.repo, self.proposals = repo, proposals

	def template(self, context, kind):
		authorize(context, "admin")
		out = io.StringIO()
		csv.writer(out).writerow(SCHEMAS[kind][0])
		return out.getvalue()

	def validate(self, context, kind, content):
		authorize(context, "admin")
		fields, required = SCHEMAS[kind]
		reader = csv.DictReader(io.StringIO(content))
		if set(reader.fieldnames or []) - set(fields) or set(required) - set(reader.fieldnames or []):
			raise ValueError("CSV columns do not match template")
		rows = []
		seen = set()
		for n, item in enumerate(reader, 2):
			data = {f: (item.get(f) or "").strip() for f in fields}
			errors = [f + " is required" for f in required if not data[f]]
			key = data[fields[0]]
			if key in seen:
				errors.append("duplicate identifier: " + key)
			seen.add(key)
			rows.append(Row(n, data, tuple(errors)))
		if not rows:
			raise ValueError("CSV requires data rows")
		return self.repo.create(context.company, kind, tuple(rows), context.user)

	def apply(self, context, batch_id):
		authorize(context, "admin")
		b = self.repo.get(context.company, batch_id)
		return (
			self.repo.apply(context.company, b.id)
			if b.status == "Validated"
			else (_ for _ in ()).throw(ValueError("Batch is not clean"))
		)

	def preview_rollback(self, context, batch_id):
		authorize(context, "admin")
		b = self.repo.get(context.company, batch_id)
		if b.status != "Applied":
			raise ValueError("Batch is not applied")
		now = datetime.now(UTC)
		p = ActionProposal(
			str(uuid4()),
			"rollback_migration",
			{"batch_id": b.id},
			RiskClass.DESTRUCTIVE,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=10),
		)
		self.proposals.save(p)
		return p

	def rollback(self, context, pid, key, engine: ActionEngine):
		p = self.proposals.load(context.company, pid)
		return engine.execute(
			p,
			key,
			lambda: self.repo.rollback(context.company, p.arguments["batch_id"]),
			approved_by=context.user,
		)
