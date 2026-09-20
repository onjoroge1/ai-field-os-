"""Deterministic approval/execution engine."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from erpnext.field_os.actions.models import ActionProposal, ExecutionReceipt
from erpnext.field_os.actions.policy import requires_confirmation


class ActionRejected(RuntimeError):
	pass


class ActionEngine:
	def __init__(self) -> None:
		self._receipts: dict[tuple[str, str, str, str], tuple[str, ExecutionReceipt]] = {}

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
		scope = (proposal.company, proposal.actor, proposal.tool, idempotency_key)
		fingerprint = json.dumps(proposal.arguments, sort_keys=True, separators=(",", ":"), default=str)
		if scope in self._receipts:
			previous_fingerprint, receipt = self._receipts[scope]
			if previous_fingerprint != fingerprint:
				raise ActionRejected("Idempotency key was already used with different arguments")
			return receipt

		result = executor()
		receipt = ExecutionReceipt(proposal.id, idempotency_key, "executed", result, now)
		self._receipts[scope] = (fingerprint, receipt)
		return receipt
