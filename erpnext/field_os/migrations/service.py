import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.actions.validation import require_proposal
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
		if kind not in SCHEMAS:
			raise ValueError("Unsupported import kind")
		fields, required = SCHEMAS[kind]
		reader = csv.DictReader(io.StringIO(content), strict=True)
		columns = reader.fieldnames or []
		if len(columns) != len(set(columns)) or set(columns) - set(fields) or set(required) - set(columns):
			raise ValueError("CSV columns do not match template")
		rows = []
		seen = set()
		for n, item in enumerate(reader, 2):
			data = {f: (item.get(f) or "").strip() for f in fields}
			errors = [f + " is required" for f in required if not data[f]]
			if None in item or any(value is None for value in item.values()):
				errors.append("row has a different number of values than the header")
			if kind == "equipment" and data["installed_on"]:
				try:
					date.fromisoformat(data["installed_on"])
				except ValueError:
					errors.append("installed_on must be an ISO date")
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
		if b.company != context.company or b.id != batch_id:
			raise ValueError("Batch is outside this tenant")
		if b.status == "Applied":
			return b
		if b.status != "Validated" or not b.rows or any(row.errors for row in b.rows):
			raise ValueError("Batch is not clean")
		return self.repo.apply(context.company, b.id)

	def preview_rollback(self, context, batch_id):
		authorize(context, "admin")
		b = self.repo.get(context.company, batch_id)
		if b.company != context.company or b.id != batch_id or b.status != "Applied":
			raise ValueError("Batch is not applied")
		now = datetime.now(UTC)
		p = ActionProposal(
			str(uuid4()),
			"rollback_migration",
			{"batch_id": b.id, "created_records": [list(record) for record in b.created]},
			RiskClass.DESTRUCTIVE,
			context.company,
			context.user,
			now,
			now + timedelta(minutes=10),
		)
		self.proposals.save(p)
		return p

	def rollback(self, context, pid, key, engine: ActionEngine):
		authorize(context, "admin")
		p = require_proposal(
			self.proposals.load(context.company, pid),
			context,
			tool="rollback_migration",
			risk=RiskClass.DESTRUCTIVE,
		)

		def execute():
			batch = self.repo.get(context.company, p.arguments["batch_id"])
			if (
				batch.company != context.company
				or batch.id != p.arguments["batch_id"]
				or batch.status != "Applied"
				or [list(record) for record in batch.created] != p.arguments.get("created_records")
			):
				raise ValueError("Batch changed; regenerate the rollback preview")
			return self.repo.rollback(context.company, batch.id)

		return engine.execute(
			p,
			key,
			execute,
			approved_by=context.user,
		)
