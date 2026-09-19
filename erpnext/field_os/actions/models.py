from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class RiskClass(StrEnum):
	READ = "read"
	LOW = "low"
	EXTERNAL = "external"
	FINANCIAL = "financial"
	DESTRUCTIVE = "destructive"


@dataclass(frozen=True, slots=True)
class ActionProposal:
	id: str
	tool: str
	arguments: dict[str, Any]
	risk: RiskClass
	company: str
	actor: str
	created_at: datetime
	expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
	proposal_id: str
	idempotency_key: str
	status: str
	result: Any
	executed_at: datetime
