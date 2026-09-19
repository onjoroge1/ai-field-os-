"""Unified Inbox endpoints."""

from __future__ import annotations

from dataclasses import asdict

import frappe

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.communications.frappe_repository import FrappeCommunicationRepository
from erpnext.field_os.communications.models import (
	CommunicationChannel,
	MessageDirection,
	ParticipantRole,
	ThreadState,
)
from erpnext.field_os.inbox.frappe_services import (
	FrappeAssigneePolicy,
	FrappeCorrectionPolicy,
	FrappeCorrectionStore,
	FrappeServiceRequestCreator,
)
from erpnext.field_os.inbox.service import InboxService
from erpnext.field_os.security.context import resolve_tenant_context

_ACTION_ENGINE = ActionEngine()


def _service() -> InboxService:
	return InboxService(
		FrappeCommunicationRepository(),
		FrappeCorrectionStore(),
		FrappeCorrectionPolicy(),
		FrappeAssigneePolicy(),
		FrappeServiceRequestCreator(),
	)


@frappe.whitelist()
def queue(
	company: str,
	states: str = "open,pending",
	channel: str | None = None,
	assignment: str = "all",
	limit: int = 50,
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	try:
		parsed_states = tuple(ThreadState(value.strip()) for value in states.split(",") if value.strip())
		parsed_channel = CommunicationChannel(channel) if channel else None
	except ValueError:
		frappe.throw("Invalid Inbox filter", frappe.ValidationError)
	if not parsed_states:
		frappe.throw("Choose at least one Inbox state", frappe.ValidationError)
	assigned_to = None
	if assignment == "mine":
		assigned_to = context.user
	elif assignment == "unassigned":
		assigned_to = ""
	elif assignment != "all":
		frappe.throw("Invalid assignment filter", frappe.ValidationError)
	return asdict(
		_service().queue(
			context,
			states=parsed_states,
			channel=parsed_channel,
			assigned_to=assigned_to,
			limit=int(limit),
		)
	)


@frappe.whitelist()
def thread(company: str, thread_id: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	return asdict(_service().detail(context, thread_id))


@frappe.whitelist(methods=["POST"])
def assign(company: str, thread_id: str, user: str, idempotency_key: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	return asdict(_service().assign(context, thread_id, user, idempotency_key, _ACTION_ENGINE))


@frappe.whitelist(methods=["POST"])
def set_state(company: str, thread_id: str, state: str, idempotency_key: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	try:
		parsed_state = ThreadState(state)
	except ValueError:
		frappe.throw("Invalid thread state", frappe.ValidationError)
	return asdict(_service().set_state(context, thread_id, parsed_state, idempotency_key, _ACTION_ENGINE))


@frappe.whitelist(methods=["POST"])
def correct(
	company: str,
	thread_id: str,
	field: str,
	value: str,
	reason: str | None = None,
	message_id: str | None = None,
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	return asdict(_service().correct(context, thread_id, field, value, reason=reason, message_id=message_id))


@frappe.whitelist(methods=["POST"])
def create_service_request(company: str, thread_id: str, idempotency_key: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	return asdict(_service().create_service_request(context, thread_id, idempotency_key, _ACTION_ENGINE))


@frappe.whitelist()
def reply_configuration(company: str, thread_id: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	detail = _service().detail(context, thread_id)
	return _reply_configuration(context, detail)


def _reply_configuration(context, detail) -> dict[str, object]:
	thread_record = detail.thread
	recipient = next(
		(item.address for item in thread_record.participants if item.role == ParticipantRole.CUSTOMER),
		None,
	)
	if not recipient:
		recipient = next(
			(item.address for item in thread_record.participants if item.role == ParticipantRole.EXTERNAL),
			None,
		)
	if not recipient:
		raise ValueError("Thread has no linked customer participant")
	latest_inbound = next(
		(
			message
			for message in reversed(detail.messages)
			if message.direction == MessageDirection.INBOUND
			and message.channel == thread_record.channel
			and message.provider
		),
		None,
	)
	if thread_record.channel == CommunicationChannel.EMAIL:
		filters = {"company": context.company, "enabled": 1}
		if latest_inbound:
			filters["name"] = latest_inbound.provider
		integration = frappe.get_all(
			"Field OS Email Integration",
			filters=filters,
			fields=["name", "from_address"],
			order_by="modified desc",
			limit=1,
		)
		if not integration:
			raise ValueError("No enabled email integration for this tenant")
		return {
			"channel": "email",
			"integration_id": integration[0].name,
			"from_address": integration[0].from_address,
			"recipient": recipient,
		}
	if thread_record.channel == CommunicationChannel.SMS:
		filters = {"company": context.company, "enabled": 1}
		if latest_inbound:
			filters["name"] = latest_inbound.provider
		integration = frappe.get_all(
			"Field OS SMS Integration",
			filters=filters,
			fields=["name", "from_number"],
			order_by="modified desc",
			limit=1,
		)
		if not integration:
			raise ValueError("No enabled SMS integration for this tenant")
		templates = frappe.get_all(
			"Field OS SMS Template",
			filters={"company": context.company, "enabled": 1},
			fields=["name", "template_name", "transactional", "variables"],
			order_by="template_name asc",
			limit=100,
		)
		return {
			"channel": "sms",
			"integration_id": integration[0].name,
			"from_number": integration[0].from_number,
			"recipient": recipient,
			"templates": templates,
		}
	raise ValueError("Replies are currently supported for email and SMS threads")


@frappe.whitelist(methods=["POST"])
def prepare_reply(
	company: str,
	thread_id: str,
	body: str,
	subject: str | None = None,
) -> dict[str, object]:
	context = resolve_tenant_context(company)
	detail = _service().detail(context, thread_id)
	if not any(message.direction == MessageDirection.INBOUND for message in detail.messages):
		raise ValueError("Transactional replies require an inbound customer message")
	configuration = _reply_configuration(context, detail)
	if configuration["channel"] == "email":
		from erpnext.field_os.api.email import _service as email_service

		message = email_service().draft(
			context,
			thread_id,
			configuration["integration_id"],
			configuration["from_address"],
			(configuration["recipient"],),
			(),
			subject or f"Re: {detail.thread.subject}",
			body,
		)
		proposal = email_service().preview_send(context, message.id or "")
	else:
		from erpnext.field_os.api.sms import _service as sms_service

		message = sms_service().draft(
			context,
			thread_id,
			configuration["integration_id"],
			configuration["from_number"],
			configuration["recipient"],
			body,
			transactional=True,
		)
		proposal = sms_service().preview_send(context, message.id or "")
	return {
		"channel": configuration["channel"],
		"integration_id": configuration["integration_id"],
		"message_id": message.id,
		"proposal": asdict(proposal),
	}
