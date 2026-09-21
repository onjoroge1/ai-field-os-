"""Ask Operations conversation endpoints."""

from __future__ import annotations

from dataclasses import asdict

import frappe
from frappe import _

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.ai.conversation import AskOperationsService, ConversationRetention
from erpnext.field_os.ai.frappe_provider import configured_provider
from erpnext.field_os.ai.frappe_store import FrappeCacheConversationStore, FrappeCacheProposalStore
from erpnext.field_os.ai.operator_catalog import build_operator_registry
from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.equipment.frappe_repository import CompanyCustomerAdapter, FrappeEquipmentRepository
from erpnext.field_os.estimates.ai import register as register_estimates
from erpnext.field_os.security.context import resolve_tenant_context

_ACTION_ENGINE = ActionEngine()


def _service(company: str) -> AskOperationsService:
	registry = build_operator_registry(CompanyCustomerAdapter(company), FrappeEquipmentRepository())
	register_estimates(registry)
	return AskOperationsService(
		configured_provider(company),
		registry,
		FrappeCacheConversationStore(),
		FrappeCacheProposalStore(),
	)


@frappe.whitelist(methods=["POST"])
@entitled
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
	response = _service(context.company).ask(
		context,
		message,
		conversation_id=conversation_id,
		retention=retention_policy,
	)
	return asdict(response)


@frappe.whitelist(methods=["POST"])
@entitled
def clear_conversation(company: str, conversation_id: str) -> dict[str, bool]:
	context = resolve_tenant_context(company)
	_service(context.company).clear(context, conversation_id)
	return {"cleared": True}


@frappe.whitelist(methods=["POST"])
@entitled
def approve(company: str, proposal_id: str, idempotency_key: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	receipt = _service(context.company).approve(context, proposal_id, idempotency_key, _ACTION_ENGINE)
	return asdict(receipt)


@frappe.whitelist(methods=["POST"])
@entitled
def reject(company: str, proposal_id: str) -> dict[str, bool]:
	context = resolve_tenant_context(company)
	_service(context.company).reject(context, proposal_id)
	return {"rejected": True}
