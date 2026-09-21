"""Dispatch board, conflict preview, and mutation endpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta

import frappe

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.dispatch.frappe_repository import FrappeDispatchRepository
from erpnext.field_os.dispatch.service import DispatchService
from erpnext.field_os.security.context import resolve_tenant_context

_ACTION_ENGINE = ActionEngine()


def _service() -> DispatchService:
	return DispatchService(FrappeDispatchRepository(), FrappeCacheProposalStore())


@frappe.whitelist()
def board(company: str, day: str | None = None) -> dict[str, object]:
	context = resolve_tenant_context(company)
	selected = date.fromisoformat(day) if day else datetime.now(UTC).date()
	start = datetime.combine(selected, time.min, tzinfo=UTC)
	return asdict(_service().board(context, start, start + timedelta(days=1)))


@frappe.whitelist(methods=["POST"])
@entitled
def preview_change(
	company: str,
	job_id: str,
	technician_id: str,
	start: str,
	end: str,
	expected_version: str | None = None,
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	preview = _service().preview_change(
		context,
		job_id,
		technician_id,
		datetime.fromisoformat(start),
		datetime.fromisoformat(end),
		expected_version,
	)
	return asdict(preview)


@frappe.whitelist(methods=["POST"])
@entitled
def commit_change(company: str, proposal_id: str, idempotency_key: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	receipt = _service().commit_change(context, proposal_id, idempotency_key, _ACTION_ENGINE)
	return asdict(receipt)
