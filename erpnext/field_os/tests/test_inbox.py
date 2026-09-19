from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationMessage,
	CommunicationParticipant,
	CommunicationThread,
	DeliveryState,
	EntityLinks,
	MessageDirection,
	ParticipantRole,
	ThreadState,
)
from erpnext.field_os.inbox.service import InboxService
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole
from erpnext.field_os.tests.test_communications import MemoryCommunicationRepository


class MemoryCorrections:
	def __init__(self):
		self.items = []

	def save(self, feedback):
		self.items.append(feedback)
		return feedback


class AllowCorrections:
	def validate(self, company, thread, field, value):
		if field not in {"classification", "customer_id"}:
			raise ValueError("unsupported")


class AllowAssignees:
	def validate(self, company, user):
		if not user.endswith("@example.test"):
			raise ValueError("invalid user")


class FakeRequestCreator:
	def __init__(self):
		self.calls = []

	def create(self, context, thread, summary):
		self.calls.append((context.company, thread.id, summary))
		return "ISSUE-1"


class TestInboxService(TestCase):
	def setUp(self):
		self.now = datetime(2026, 9, 19, 15, tzinfo=UTC)
		self.repository = MemoryCommunicationRepository()
		self.corrections = MemoryCorrections()
		self.creator = FakeRequestCreator()
		self.service = InboxService(
			self.repository,
			self.corrections,
			AllowCorrections(),
			AllowAssignees(),
			self.creator,
		)
		self.context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		self.sender = CommunicationParticipant("customer@example.test", ParticipantRole.CUSTOMER, "Acme")

	def add_thread(
		self, subject, *, due_at, assigned_to=None, classification="service_request", customer="CUST-1"
	):
		thread = self.repository.save_thread(
			CommunicationThread(
				None,
				"HVAC CO",
				subject,
				CommunicationChannel.EMAIL,
				ThreadState.OPEN,
				(self.sender,),
				EntityLinks(customer_id=customer),
				assigned_to,
				classification,
				due_at,
				self.now - timedelta(minutes=20),
			)
		)
		message = self.repository.save_message(
			CommunicationMessage(
				None,
				"HVAC CO",
				thread.id,
				CommunicationChannel.EMAIL,
				MessageDirection.INBOUND,
				self.sender,
				(),
				"The unit is not cooling.",
				self.now - timedelta(minutes=20),
				DeliveryState.RECEIVED,
			)
		)
		return thread, message

	def test_queue_prioritizes_overdue_and_suggests_next_actions(self):
		on_track, _ = self.add_thread(
			"Later", due_at=self.now + timedelta(hours=3), assigned_to="d@example.test"
		)
		overdue, _ = self.add_thread("Urgent", due_at=self.now - timedelta(minutes=1), customer=None)
		queue = self.service.queue(self.context, now=self.now)
		self.assertEqual([item.thread.id for item in queue.items], [overdue.id, on_track.id])
		self.assertEqual(queue.counts["overdue"], 1)
		self.assertEqual(queue.counts["unassigned"], 1)
		self.assertEqual(
			[action.kind for action in queue.items[0].suggestions],
			["assign", "reply", "correct"],
		)

	def test_unsupported_channel_does_not_suggest_reply(self):
		thread, _ = self.add_thread("Web", due_at=self.now + timedelta(hours=1))
		self.repository.threads[(thread.company, thread.id)] = replace(
			thread, channel=CommunicationChannel.WEB
		)
		queue = self.service.queue(self.context, now=self.now)
		self.assertNotIn("reply", [action.kind for action in queue.items[0].suggestions])

	def test_assignment_and_state_change_are_idempotent_actions(self):
		thread, _ = self.add_thread("Assign", due_at=self.now + timedelta(hours=1))
		engine = ActionEngine()
		first = self.service.assign(self.context, thread.id, "owner@example.test", "assign:1", engine)
		second = self.service.assign(self.context, thread.id, "owner@example.test", "assign:1", engine)
		self.assertEqual(first, second)
		self.assertEqual(self.repository.get_thread("HVAC CO", thread.id).assigned_to, "owner@example.test")
		self.service.set_state(self.context, thread.id, ThreadState.CLOSED, "state:1", engine)
		self.assertEqual(self.repository.get_thread("HVAC CO", thread.id).state, ThreadState.CLOSED)

	def test_correction_updates_thread_and_records_feedback(self):
		thread, message = self.add_thread("Correct", due_at=self.now + timedelta(hours=1))
		feedback = self.service.correct(
			self.context,
			thread.id,
			"classification",
			"billing",
			reason="Operator knows this is billing",
			message_id=message.id,
		)
		self.assertEqual(feedback.previous_value, "service_request")
		self.assertEqual(self.repository.get_thread("HVAC CO", thread.id).classification, "billing")
		self.assertEqual(self.corrections.items, [feedback])

	def test_correction_message_must_belong_to_thread(self):
		thread, _ = self.add_thread("Correct", due_at=self.now + timedelta(hours=1))
		other, other_message = self.add_thread("Other", due_at=self.now + timedelta(hours=1))
		with self.assertRaises(ValueError):
			self.service.correct(
				self.context,
				thread.id,
				"classification",
				"billing",
				message_id=other_message.id,
			)
		self.assertEqual(self.repository.get_thread("HVAC CO", thread.id).classification, "service_request")
		self.assertEqual(self.repository.get_thread("HVAC CO", other.id).classification, "service_request")

	def test_create_request_links_result_once(self):
		thread, _ = self.add_thread("Create", due_at=self.now + timedelta(hours=1))
		receipt = self.service.create_service_request(self.context, thread.id, "request:1", ActionEngine())
		self.assertEqual(receipt.result["service_request_id"], "ISSUE-1")
		self.assertEqual(self.repository.get_thread("HVAC CO", thread.id).links.service_request_id, "ISSUE-1")
		self.assertEqual(len(self.creator.calls), 1)

	def test_cross_tenant_thread_is_not_visible(self):
		thread, _ = self.add_thread("Tenant", due_at=self.now)
		self.repository.threads[("OTHER CO", thread.id)] = replace(thread, company="OTHER CO")
		other = TenantContext("OTHER CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		queue = self.service.queue(other, now=self.now)
		self.assertEqual([item.thread.company for item in queue.items], ["OTHER CO"])
