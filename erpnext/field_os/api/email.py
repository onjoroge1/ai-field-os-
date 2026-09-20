"""Inbound, delivery, draft, and approved outbound email endpoints."""

from __future__ import annotations

import json
from dataclasses import asdict

import frappe
from frappe import _

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.communications.email import EmailService
from erpnext.field_os.communications.email_frappe import (
	FrappeEmailEntityResolver,
	configured_classifier,
	load_email_integration,
)
from erpnext.field_os.communications.frappe_repository import FrappeCommunicationRepository
from erpnext.field_os.security.context import resolve_tenant_context

_ACTION_ENGINE = ActionEngine()


def _service() -> EmailService:
	return EmailService(
		FrappeCommunicationRepository(),
		configured_classifier(),
		FrappeEmailEntityResolver(),
		FrappeCacheProposalStore(),
	)


def _raw_request() -> tuple[bytes, dict[str, str]]:
	if not getattr(frappe.local, "request", None):
		raise ValueError("Webhook request context is required")
	return frappe.request.get_data(), dict(frappe.request.headers)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def inbound_webhook(mailbox_key: str) -> dict[str, object]:
	integration = load_email_integration(mailbox_key=mailbox_key)
	raw_body, headers = _raw_request()
	email = integration.provider.verify_and_parse_inbound(raw_body, headers, integration.webhook_secret)
	result = _service().receive(integration.company, integration.id, email)
	return {"accepted": True, "created": result.created, "message_id": result.message.id}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def delivery_webhook(mailbox_key: str) -> dict[str, object]:
	integration = load_email_integration(mailbox_key=mailbox_key)
	raw_body, headers = _raw_request()
	event = integration.provider.verify_and_parse_delivery(raw_body, headers, integration.webhook_secret)
	message = _service().apply_delivery_event(integration.company, integration.id, event)
	return {"accepted": True, "message_id": message.id, "state": message.delivery_state.value}


@frappe.whitelist(methods=["POST"])
def create_draft(
	company: str,
	thread_id: str,
	integration_id: str,
	to: str,
	subject: str,
	body: str,
	cc: str | None = None,
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	integration = load_email_integration(integration_id=integration_id)
	if integration.company != context.company:
		raise frappe.PermissionError("Email integration belongs to another tenant")
	to_payload = json.loads(to)
	cc_payload = json.loads(cc or "[]")
	if not isinstance(to_payload, list) or not isinstance(cc_payload, list):
		frappe.throw(_("Email recipients must be JSON arrays"), frappe.ValidationError)
	to_addresses = tuple(str(item).strip() for item in to_payload if str(item).strip())
	cc_addresses = tuple(str(item).strip() for item in cc_payload if str(item).strip())
	message = _service().draft(
		context,
		thread_id,
		integration.id,
		integration.from_address,
		to_addresses,
		cc_addresses,
		subject,
		body,
	)
	return asdict(message)


@frappe.whitelist(methods=["POST"])
def preview_send(company: str, message_id: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	return asdict(_service().preview_send(context, message_id))


@frappe.whitelist(methods=["POST"])
def approve_send(
	company: str, proposal_id: str, integration_id: str, idempotency_key: str
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	from erpnext.field_os.demo.safety import block_delivery

	block_delivery(context.company)
	integration = load_email_integration(integration_id=integration_id)
	if integration.company != context.company:
		raise frappe.PermissionError("Email integration belongs to another tenant")
	receipt = _service().approve_send(
		context,
		proposal_id,
		idempotency_key,
		integration.provider,
		integration.id,
		integration.from_address,
		_ACTION_ENGINE,
	)
	return asdict(receipt)


def poll_enabled_mailboxes() -> None:
	for name in frappe.get_all(
		"Field OS Email Integration", filters={"enabled": 1, "poll_enabled": 1}, pluck="name"
	):
		try:
			integration = load_email_integration(integration_id=name)
			emails, cursor = integration.provider.poll(integration.poll_cursor, 100)
			service = _service()
			for email in emails:
				service.receive(integration.company, integration.id, email)
			frappe.db.set_value(
				"Field OS Email Integration",
				name,
				{"poll_cursor": cursor, "last_error": None},
				update_modified=False,
			)
		except Exception:
			error = frappe.get_traceback(with_context=False)
			frappe.db.set_value(
				"Field OS Email Integration",
				name,
				{"last_error": error[-2000:]},
				update_modified=False,
			)
			frappe.log_error(title=f"Field OS email poll failed: {name}")
