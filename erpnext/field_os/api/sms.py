"""Inbound, delivery, templating, and approved outbound SMS endpoints."""

from __future__ import annotations

import json
from dataclasses import asdict

import frappe
from frappe import _

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.communications.email_frappe import configured_classifier
from erpnext.field_os.communications.frappe_repository import FrappeCommunicationRepository
from erpnext.field_os.communications.sms import SMSService, render_sms_template
from erpnext.field_os.communications.sms_frappe import (
	FrappeSMSEntityResolver,
	load_sms_integration,
	load_sms_template,
)
from erpnext.field_os.jobs.service import DurableSender
from erpnext.field_os.security.context import resolve_tenant_context

_ACTION_ENGINE = ActionEngine()


def _service(company=None) -> SMSService:
	return SMSService(
		FrappeCommunicationRepository(),
		configured_classifier(company),
		FrappeSMSEntityResolver(),
		FrappeCacheProposalStore(),
	)


def _raw_request() -> tuple[bytes, dict[str, str]]:
	if not getattr(frappe.local, "request", None):
		raise ValueError("Webhook request context is required")
	return frappe.request.get_data(), dict(frappe.request.headers)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def inbound_webhook(endpoint_key: str) -> dict[str, object]:
	integration = load_sms_integration(endpoint_key=endpoint_key)
	raw_body, headers = _raw_request()
	sms = integration.provider.verify_and_parse_inbound(raw_body, headers, integration.webhook_secret)
	result = _service().receive(integration.company, integration.id, sms)
	return {
		"accepted": True,
		"created": result.ingest.created,
		"message_id": result.ingest.message.id,
		"consent_state": result.consent_state.value if result.consent_state else None,
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def delivery_webhook(endpoint_key: str) -> dict[str, object]:
	integration = load_sms_integration(endpoint_key=endpoint_key)
	raw_body, headers = _raw_request()
	event = integration.provider.verify_and_parse_delivery(raw_body, headers, integration.webhook_secret)
	message = _service().apply_delivery_event(integration.company, integration.id, event)
	return {"accepted": True, "message_id": message.id, "state": message.delivery_state.value}


@frappe.whitelist(methods=["POST"])
@entitled
def create_draft(
	company: str,
	thread_id: str,
	integration_id: str,
	to_number: str,
	body: str | None = None,
	template_id: str | None = None,
	variables: str | None = None,
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	integration = load_sms_integration(integration_id=integration_id)
	if integration.company != context.company:
		raise frappe.PermissionError("SMS integration belongs to another tenant")
	if bool(body) == bool(template_id):
		frappe.throw(_("Provide either body or template_id"), frappe.ValidationError)
	if template_id:
		template = load_sms_template(context.company, template_id)
		payload = json.loads(variables or "{}")
		if not isinstance(payload, dict) or any(
			not isinstance(value, str | int | float) for value in payload.values()
		):
			frappe.throw(_("SMS template variables must be a simple JSON object"), frappe.ValidationError)
		body = render_sms_template(template, {key: str(value) for key, value in payload.items()})
		transactional = bool(template.transactional)
	else:
		transactional = False
	message = _service(context.company).draft(
		context,
		thread_id,
		integration.id,
		integration.from_number,
		to_number,
		body or "",
		transactional=transactional,
	)
	return asdict(message)


@frappe.whitelist(methods=["POST"])
@entitled
def preview_send(company: str, message_id: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	return asdict(_service(context.company).preview_send(context, message_id))


@frappe.whitelist(methods=["POST"])
@entitled
def approve_send(
	company: str, proposal_id: str, integration_id: str, idempotency_key: str
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	from erpnext.field_os.demo.safety import block_delivery

	block_delivery(context.company)
	integration = load_sms_integration(integration_id=integration_id)
	if integration.company != context.company:
		raise frappe.PermissionError("SMS integration belongs to another tenant")
	receipt = _service(context.company).approve_send(
		context,
		proposal_id,
		idempotency_key,
		DurableSender(context, "sms", integration.id),
		integration.id,
		integration.from_number,
		_ACTION_ENGINE,
	)
	return asdict(receipt)
