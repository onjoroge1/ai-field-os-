from dataclasses import dataclass
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
		if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
			raise ValueError("Setup data must be a list of records")
		if step == "users":
			for item in payload:
				roles = item.get("roles")
				if (
					not isinstance(roles, list)
					or not roles
					or any(
						not isinstance(role, str) or role not in {r.value for r in FieldOSRole}
						for role in roles
					)
				):
					raise ValueError("Invalid Field OS role")
		return self.repo.save(context.company, step, payload)

	def complete(self, context):
		authorize(context, "admin")
		state = self.repo.state(context.company)
		if state.company != context.company:
			raise ValueError("Setup state is outside this tenant")
		missing = [x for x in self.steps if x not in state.completed_steps]
		if missing:
			raise ValueError("Missing steps: " + ", ".join(missing))
		checks = self.repo.checks(context.company)
		if not checks:
			raise ValueError("Integration checks have not run")
		failed = [k for k, v in checks.items() if v is not True]
		if failed:
			raise ValueError("Integration checks failed: " + ", ".join(failed))
		return self.repo.complete(context.company)
