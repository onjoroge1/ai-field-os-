"""Ask Operations conversation endpoints."""

from __future__ import annotations

from dataclasses import asdict

import frappe
from frappe import _

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.adapter.erpnext import ERPNextAdapter
from erpnext.field_os.ai.conversation import AskOperationsService, ConversationRetention
from erpnext.field_os.ai.frappe_provider import configured_provider
from erpnext.field_os.ai.frappe_store import FrappeCacheConversationStore, FrappeCacheProposalStore
from erpnext.field_os.ai.operator_catalog import build_operator_registry
from erpnext.field_os.security.context import resolve_tenant_context

_ACTION_ENGINE = ActionEngine()


def _service() -> AskOperationsService:
	return AskOperationsService(
		configured_provider(),
		build_operator_registry(ERPNextAdapter()),
		FrappeCacheConversationStore(),
		FrappeCacheProposalStore(),
	)


@frappe.whitelist()
def ask(
	company: str,
	message: str,
	conversation_id: str | None = None,
	retention: str = ConversationRetention.SESSION.value,
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	try:
		retention_policy = ConversationRetention(retention)
	except ValueError:
		frappe.throw(_("Invalid conversation retention policy"), frappe.ValidationError)
	response = _service().ask(
		context,
		message,
		conversation_id=conversation_id,
		retention=retention_policy,
	)
	return asdict(response)


@frappe.whitelist(methods=["POST"])
def clear_conversation(company: str, conversation_id: str) -> dict[str, bool]:
	context = resolve_tenant_context(company)
	_service().clear(context, conversation_id)
	return {"cleared": True}


@frappe.whitelist(methods=["POST"])
def approve(company: str, proposal_id: str, idempotency_key: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	receipt = _service().approve(context, proposal_id, idempotency_key, _ACTION_ENGINE)
	return asdict(receipt)


@frappe.whitelist(methods=["POST"])
def reject(company: str, proposal_id: str) -> dict[str, bool]:
	context = resolve_tenant_context(company)
	_service().reject(context, proposal_id)
	return {"rejected": True}
