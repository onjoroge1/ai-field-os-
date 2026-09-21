"""Frappe persistence for the normalized communication model."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone

from erpnext.field_os.communications.models import (
	CommunicationAttachment,
	CommunicationChannel,
	CommunicationMessage,
	CommunicationParticipant,
	CommunicationThread,
	ConsentState,
	ContactPreference,
	DeliveryState,
	EntityLinks,
	MessageDirection,
	ParticipantRole,
	ThreadState,
)


def _database_time(value):
	if value is None:
		return None
	value = get_datetime(value)
	if value.tzinfo is not None:
		return value.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	return value


def _domain_time(value):
	if value is None:
		return None
	value = get_datetime(value)
	if value.tzinfo is None:
		value = value.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return value.astimezone(UTC)


def _value(row: Any, key: str, default=None):
	return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _participant(row) -> CommunicationParticipant:
	return CommunicationParticipant(
		_value(row, "address"),
		ParticipantRole(_value(row, "participant_role")),
		_value(row, "display_name"),
		_value(row, "contact"),
	)


class FrappeCommunicationRepository:
	def get_thread(self, company, thread_id):
		if not thread_id or not frappe.db.exists(
			"Field OS Communication Thread", {"name": thread_id, "company": company}
		):
			return None
		return self._thread(frappe.get_doc("Field OS Communication Thread", thread_id))

	def find_thread_by_external_id(self, company, channel, external_thread_id):
		name = frappe.db.get_value(
			"Field OS Communication Thread",
			{"company": company, "channel": channel.value, "external_thread_id": external_thread_id},
			"name",
		)
		return self.get_thread(company, name) if name else None

	def save_thread(self, thread):
		values = {
			"company": thread.company,
			"subject": thread.subject,
			"channel": thread.channel.value,
			"status": thread.state.value,
			"classification": thread.classification,
			"assigned_to": thread.assigned_to,
			"sla_due_at": _database_time(thread.sla_due_at),
			"last_message_at": _database_time(thread.last_message_at),
			"external_thread_id": thread.external_thread_id,
			"customer": thread.links.customer_id,
			"site": thread.links.site_id,
			"equipment": thread.links.equipment_id,
			"service_request": thread.links.service_request_id,
			"job": thread.links.job_id,
			"quote": thread.links.quote_id,
			"invoice": thread.links.invoice_id,
		}
		participants = [
			{
				"address": participant.address,
				"participant_role": participant.role.value,
				"display_name": participant.display_name,
				"contact": participant.contact_id,
			}
			for participant in thread.participants
		]
		if thread.id:
			doc = frappe.get_doc("Field OS Communication Thread", thread.id)
			if doc.company != thread.company:
				raise PermissionError("Cross-tenant thread update rejected")
			doc.update(values)
			doc.set("participants", participants)
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc(
				{"doctype": "Field OS Communication Thread", **values, "participants": participants}
			)
			doc.insert(ignore_permissions=True)
		return self._thread(doc)

	def list_threads(self, company, *, states=(), channel=None, assigned_to=None, limit=50):
		filters = {"company": company}
		if states:
			filters["status"] = ["in", list(states)]
		if channel:
			filters["channel"] = channel.value
		if assigned_to is not None:
			filters["assigned_to"] = ["in", ["", None]] if assigned_to == "" else assigned_to
		names = frappe.get_all(
			"Field OS Communication Thread",
			filters=filters,
			pluck="name",
			order_by="last_message_at desc, modified desc",
			limit=max(1, min(limit, 100)),
		)
		return [self._thread(frappe.get_doc("Field OS Communication Thread", name)) for name in names]

	def find_message_by_dedupe(self, company, dedupe_key):
		name = frappe.db.get_value(
			"Field OS Communication Message", {"company": company, "dedupe_key": dedupe_key}, "name"
		)
		return self._message(frappe.get_doc("Field OS Communication Message", name)) if name else None

	def get_message(self, company, message_id):
		if not message_id or not frappe.db.exists(
			"Field OS Communication Message", {"name": message_id, "company": company}
		):
			return None
		return self._message(frappe.get_doc("Field OS Communication Message", message_id))

	def find_message_by_external_id(self, company, channel, external_id, provider=None):
		filters = {"company": company, "channel": channel.value, "external_id": external_id}
		if provider:
			filters["provider"] = provider
		name = frappe.db.get_value(
			"Field OS Communication Message",
			filters,
			"name",
		)
		return self.get_message(company, name) if name else None

	def save_message(self, message):
		if not message.thread_id:
			raise ValueError("Message thread is required")
		thread_company = frappe.db.get_value("Field OS Communication Thread", message.thread_id, "company")
		if thread_company != message.company:
			raise PermissionError("Cross-tenant message rejected")
		values = {
			"doctype": "Field OS Communication Message",
			"company": message.company,
			"thread": message.thread_id,
			"channel": message.channel.value,
			"direction": message.direction.value,
			"sender_address": message.sender.address,
			"sender_name": message.sender.display_name,
			"sender_role": message.sender.role.value,
			"recipients_json": json.dumps([asdict(item) for item in message.recipients]),
			"subject": message.subject,
			"body": message.body,
			"occurred_at": _database_time(message.occurred_at),
			"delivery_status": message.delivery_state.value,
			"external_id": message.external_id,
			"dedupe_key": message.dedupe_key,
			"provider": message.provider,
			"classification": message.classification,
			"provider_metadata_json": json.dumps(message.metadata),
			"error": message.error,
			"attachments": [
				{
					"filename": item.filename,
					"content_type": item.content_type,
					"size_bytes": item.size_bytes,
					"file": item.file_id,
					"external_url": item.external_url,
				}
				for item in message.attachments
			],
		}
		if message.id:
			doc = frappe.get_doc("Field OS Communication Message", message.id)
			if doc.company != message.company:
				raise PermissionError("Cross-tenant message update rejected")
			doc.update(values)
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc(values)
			doc.insert(ignore_permissions=True)
		return self._message(doc)

	def list_messages(self, company, thread_id, limit=100):
		if not self.get_thread(company, thread_id):
			return []
		names = frappe.get_all(
			"Field OS Communication Message",
			filters={"company": company, "thread": thread_id},
			pluck="name",
			order_by="occurred_at asc, creation asc",
			limit=max(1, min(limit, 500)),
		)
		return [self._message(frappe.get_doc("Field OS Communication Message", name)) for name in names]

	def get_preference(self, company, channel, address):
		name = frappe.db.get_value(
			"Field OS Contact Preference",
			{"company": company, "channel": channel.value, "contact_address": address},
			"name",
		)
		if not name:
			return None
		doc = frappe.get_doc("Field OS Contact Preference", name)
		return ContactPreference(
			doc.company,
			doc.contact_address,
			CommunicationChannel(doc.channel),
			ConsentState(doc.consent_status),
			doc.source,
			_domain_time(doc.updated_at),
			doc.proof,
		)

	def save_preference(self, preference):
		filters = {
			"company": preference.company,
			"channel": preference.channel.value,
			"contact_address": preference.address,
		}
		name = frappe.db.get_value("Field OS Contact Preference", filters, "name")
		doc = (
			frappe.get_doc("Field OS Contact Preference", name)
			if name
			else frappe.new_doc("Field OS Contact Preference")
		)
		doc.update(
			{
				**filters,
				"consent_status": preference.state.value,
				"source": preference.source,
				"updated_at": _database_time(preference.updated_at),
				"proof": preference.proof,
			}
		)
		doc.save(ignore_permissions=True) if name else doc.insert(ignore_permissions=True)
		return preference

	@staticmethod
	def _thread(doc):
		return CommunicationThread(
			doc.name,
			doc.company,
			doc.subject,
			CommunicationChannel(doc.channel),
			ThreadState(doc.status),
			tuple(_participant(item) for item in doc.participants),
			EntityLinks(
				doc.customer, doc.site, doc.equipment, doc.service_request, doc.job, doc.quote, doc.invoice
			),
			doc.assigned_to,
			doc.classification,
			_domain_time(doc.sla_due_at),
			_domain_time(doc.last_message_at),
			doc.external_thread_id,
		)

	@staticmethod
	def _message(doc):
		recipients = json.loads(doc.recipients_json or "[]")
		return CommunicationMessage(
			doc.name,
			doc.company,
			doc.thread,
			CommunicationChannel(doc.channel),
			MessageDirection(doc.direction),
			CommunicationParticipant(doc.sender_address, ParticipantRole(doc.sender_role), doc.sender_name),
			tuple(
				CommunicationParticipant(
					item["address"],
					ParticipantRole(item.get("role") or item["participant_role"]),
					item.get("display_name"),
					item.get("contact_id"),
				)
				for item in recipients
			),
			doc.body,
			_domain_time(doc.occurred_at),
			DeliveryState(doc.delivery_status),
			doc.subject,
			doc.external_id,
			doc.dedupe_key,
			doc.provider,
			tuple(
				CommunicationAttachment(
					item.filename, item.content_type, item.size_bytes, item.file, item.external_url
				)
				for item in doc.attachments
			),
			doc.classification,
			json.loads(doc.provider_metadata_json or "{}"),
			doc.error,
		)
