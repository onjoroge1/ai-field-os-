from dataclasses import asdict, dataclass
from typing import Protocol

from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.roles import FieldOSRole


@dataclass(frozen=True, slots=True)
class State:
	company: str
	status: str
	completed_steps: tuple[str, ...]


class Repo(Protocol):
	def state(self, company: str) -> State:
		...

	def save(self, company: str, step: str, payload: list[dict]) -> State:
		...

	def checks(self, company: str) -> dict[str, bool]:
		...

	def complete(self, company: str) -> State:
		...


class OnboardingService:
	steps = ("company", "users", "services", "notifications")

	def __init__(self, repo: Repo):
		self.repo = repo

	def configure(self, context, step, payload):
		authorize(context, "admin")
		if step not in self.steps or not payload:
			raise ValueError("Valid setup data is required")
		if step == "users" and any(not set(x["roles"]) <= {r.value for r in FieldOSRole} for x in payload):
			raise ValueError("Invalid Field OS role")
		return self.repo.save(context.company, step, payload)

	def complete(self, context):
		authorize(context, "admin")
		state = self.repo.state(context.company)
		missing = [x for x in self.steps if x not in state.completed_steps]
		if missing:
			raise ValueError("Missing steps: " + ", ".join(missing))
		failed = [k for k, v in self.repo.checks(context.company).items() if not v]
		if failed:
			raise ValueError("Integration checks failed: " + ", ".join(failed))
		return self.repo.complete(context.company)
