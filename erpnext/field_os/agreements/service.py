from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from erpnext.field_os.security.authorization import authorize


@dataclass(frozen=True, slots=True)
class Agreement:
	id: str
	company: str
	customer_id: str
	site_id: str
	status: str
	starts_on: date
	ends_on: date
	interval_months: int
	renewal_notice_days: int = 30


@dataclass(frozen=True, slots=True)
class DueVisit:
	agreement_id: str
	due_on: date
	state: str


class Repository(Protocol):
	def list(self, company: str) -> list[Agreement]:
		...

	def completed(self, company: str, agreement_id: str) -> list[date]:
		...


def add_months(value, months):
	i = value.month - 1 + months
	y = value.year + i // 12
	m = i % 12 + 1
	return date(y, m, min(value.day, calendar.monthrange(y, m)[1]))


class AgreementService:
	def __init__(self, repo: Repository):
		self.repo = repo

	def dashboard(self, context, today):
		authorize(context, "read")
		active = [x for x in self.repo.list(context.company) if x.status == "Active"]
		due = []
		for item in active:
			when = add_months(
				max(self.repo.completed(context.company, item.id), default=item.starts_on),
				item.interval_months,
			)
			if when <= item.ends_on and when <= add_months(today, 1):
				due.append(DueVisit(item.id, when, "Overdue" if when < today else "Due"))
		return {
			"active": len(active),
			"due": tuple(x for x in due if x.state == "Due"),
			"overdue": tuple(x for x in due if x.state == "Overdue"),
			"renewals": tuple(x for x in active if (x.ends_on - today).days <= x.renewal_notice_days),
		}
