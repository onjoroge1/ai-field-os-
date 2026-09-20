from dataclasses import replace
from datetime import UTC, datetime
from unittest import TestCase

from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationMessage,
	CommunicationParticipant,
	CommunicationThread,
	ConsentState,
	DeliveryState,
	EntityLinks,
	MessageDirection,
	ParticipantRole,
	ThreadState,
)
from erpnext.field_os.communications.service import CommunicationService, normalize_address
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class MemoryCommunicationRepository:
	def __init__(self):
		self.threads = {}
		self.messages = {}
		self.preferences = {}

	def get_thread(self, company, thread_id):
		return self.threads.get((company, thread_id))

	def find_thread_by_external_id(self, company, channel, external_thread_id):
		return next(
			(
				thread
				for (tenant, _), thread in self.threads.items()
				if tenant == company
				and thread.channel == channel
				and thread.external_thread_id == external_thread_id
			),
			None,
		)

	def save_thread(self, thread):
		thread = thread if thread.id else replace(thread, id=f"THREAD-{len(self.threads) + 1}")
		self.threads[(thread.company, thread.id)] = thread
		return thread

	def list_threads(self, company, *, states=(), channel=None, assigned_to=None, limit=50):
		items = [thread for (tenant, _), thread in self.threads.items() if tenant == company]
		if states:
			items = [thread for thread in items if thread.state.value in states]
		if channel:
			items = [thread for thread in items if thread.channel == channel]
		if assigned_to is not None:
			items = [thread for thread in items if thread.assigned_to == assigned_to]
		return items[:limit]

	def find_message_by_dedupe(self, company, dedupe_key):
		return next(
			(
				message
				for (tenant, _), message in self.messages.items()
				if tenant == company and message.dedupe_key == dedupe_key
			),
			None,
		)

	def get_message(self, company, message_id):
		return self.messages.get((company, message_id))

	def find_message_by_external_id(self, company, channel, external_id, provider=None):
		return next(
			(
				message
				for (tenant, _), message in self.messages.items()
				if tenant == company
				and message.channel == channel
				and message.external_id == external_id
				and (not provider or message.provider == provider)
			),
			None,
		)

	def save_message(self, message):
		message = message if message.id else replace(message, id=f"MESSAGE-{len(self.messages) + 1}")
		self.messages[(message.company, message.id)] = message
		return message

	def list_messages(self, company, thread_id, limit=100):
		return [
			message
			for (tenant, _), message in self.messages.items()
			if tenant == company and message.thread_id == thread_id
		][:limit]

	def get_preference(self, company, channel, address):
		return self.preferences.get((company, channel, address))

	def save_preference(self, preference):
		self.preferences[(preference.company, preference.channel, preference.address)] = preference
		return preference


class TestCommunicationService(TestCase):
	def setUp(self):
		self.repository = MemoryCommunicationRepository()
		self.service = CommunicationService(self.repository)
		self.customer = CommunicationParticipant("CUSTOMER@EXAMPLE.TEST", ParticipantRole.CUSTOMER, "Acme")
		self.thread = CommunicationThread(
			None,
			"HVAC CO",
			"RTU is not cooling",
			CommunicationChannel.EMAIL,
			ThreadState.OPEN,
			(self.customer,),
			EntityLinks(customer_id="CUST-1"),
			external_thread_id="provider-thread-1",
		)
		self.message = CommunicationMessage(
			None,
			"HVAC CO",
			None,
			CommunicationChannel.EMAIL,
			MessageDirection.INBOUND,
			self.customer,
			(),
			"The rooftop unit is warm.",
			datetime(2026, 9, 19, 14, tzinfo=UTC),
			DeliveryState.RECEIVED,
			"RTU is not cooling",
			"provider-message-1",
			"email:provider-message-1",
		)

	def test_ingest_is_deduplicated_and_updates_thread(self):
		first = self.service.ingest(self.thread, self.message)
		second = self.service.ingest(self.thread, self.message)
		self.assertTrue(first.created)
		self.assertFalse(second.created)
		self.assertEqual(first.message.id, second.message.id)
		self.assertEqual(first.thread.last_message_at, self.message.occurred_at)
		self.assertEqual(len(self.repository.messages), 1)

	def test_cross_tenant_message_is_rejected(self):
		with self.assertRaises(PermissionError):
			self.service.ingest(self.thread, replace(self.message, company="OTHER CO"))

	def test_sms_marketing_requires_opt_in_and_stop_wins(self):
		context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		self.assertFalse(
			self.service.can_send("HVAC CO", "(404) 555-1000", CommunicationChannel.SMS, transactional=False)
		)
		preference = self.service.set_preference(
			context,
			"(404) 555-1000",
			CommunicationChannel.SMS,
			ConsentState.OPTED_IN,
			"web_form",
		)
		self.assertEqual(preference.address, "4045551000")
		self.assertTrue(
			self.service.can_send("HVAC CO", "404-555-1000", CommunicationChannel.SMS, transactional=False)
		)
		self.service.set_preference(
			context,
			"4045551000",
			CommunicationChannel.SMS,
			ConsentState.OPTED_OUT,
			"inbound_stop",
		)
		self.assertFalse(
			self.service.can_send("HVAC CO", "4045551000", CommunicationChannel.SMS, transactional=True)
		)

	def test_address_normalization_is_channel_specific(self):
		self.assertEqual(
			normalize_address(CommunicationChannel.EMAIL, " Ops@Example.TEST "), "ops@example.test"
		)
		self.assertEqual(normalize_address(CommunicationChannel.SMS, "+1 (404) 555-1000"), "+14045551000")
