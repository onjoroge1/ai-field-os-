"""Deterministic approval/execution engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt
from erpnext.field_os.actions.policy import requires_confirmation


class ActionRejected(RuntimeError):
	pass


class ActionEngine:
	def __init__(self) -> None:
		self._receipts: dict[str, ExecutionReceipt] = {}

	def execute(
		self,
		proposal: ActionProposal,
		idempotency_key: str,
		executor: Callable[[], Any],
		*,
		approved_by: str | None = None,
		now: datetime | None = None,
	) -> ExecutionReceipt:
		now = now or datetime.now(UTC)
		if proposal.expires_at <= now:
			raise ActionRejected("Proposal is stale; regenerate before execution")
		if requires_confirmation(proposal.risk) and not approved_by:
			raise ActionRejected("Explicit approval is required")
		if not idempotency_key:
			raise ActionRejected("Idempotency key is required")
		if idempotency_key in self._receipts:
			return self._receipts[idempotency_key]

		result = executor()
		receipt = ExecutionReceipt(proposal.id, idempotency_key, "executed", result, now)
		self._receipts[idempotency_key] = receipt
		return receipt
