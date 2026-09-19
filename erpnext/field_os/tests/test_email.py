import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.communications.email import (
	DeterministicEmailClassifier,
	EmailDeliveryEvent,
	EmailSendResult,
	EmailService,
	FrappeEmailProvider,
	InboundEmail,
)
from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationParticipant,
	CommunicationThread,
	DeliveryState,
	EntityLinks,
	ParticipantRole,
	ThreadState,
)
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole
from erpnext.field_os.tests.test_communications import MemoryCommunicationRepository


class FakeProposalStore:
	def __init__(self):
		self.items = {}

	def save(self, proposal):
		self.items[(proposal.company, proposal.id)] = proposal

	def load(self, company, proposal_id):
		return self.items.get((company, proposal_id))

	def delete(self, company, proposal_id):
		self.items.pop((company, proposal_id), None)


class FakeResolver:
	def resolve(self, company, sender_address):
		return EntityLinks(customer_id="CUST-1") if sender_address == "ops@acme.test" else EntityLinks()


class FakeEmailProvider:
	def __init__(self, fail=False):
		self.fail = fail
		self.sent = []

	def send(self, email):
		self.sent.append(email)
		if self.fail:
			raise RuntimeError("provider unavailable")
		return EmailSendResult("provider-123", DeliveryState.SENT, datetime.now(UTC), {"accepted": True})


class TestEmailWorkflow(TestCase):
	def setUp(self):
		self.repository = MemoryCommunicationRepository()
		self.proposals = FakeProposalStore()
		self.service = EmailService(
			self.repository,
			DeterministicEmailClassifier(),
			FakeResolver(),
			self.proposals,
		)
		self.context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))

	def test_inbound_is_classified_linked_threaded_and_deduped(self):
		email = InboundEmail(
			"message-1",
			"thread-1",
			"ops@acme.test",
			"Acme Ops",
			("dispatch@hvac.test",),
			(),
			"No cooling in server room",
			"The rooftop unit is not cooling.",
			datetime(2026, 9, 19, 14, tzinfo=UTC),
		)
		first = self.service.receive("HVAC CO", "EMAIL-1", email)
		second = self.service.receive("HVAC CO", "EMAIL-1", email)
		self.assertTrue(first.created)
		self.assertFalse(second.created)
		self.assertEqual(first.thread.links.customer_id, "CUST-1")
		self.assertEqual(first.thread.classification, "service_request")
		self.assertEqual(first.message.classification, "service_request")

	def test_draft_requires_approval_then_sends_once(self):
		thread = self.repository.save_thread(
			CommunicationThread(
				None,
				"HVAC CO",
				"Appointment",
				CommunicationChannel.EMAIL,
				ThreadState.OPEN,
				(CommunicationParticipant("customer@example.test", ParticipantRole.CUSTOMER),),
			)
		)
		draft = self.service.draft(
			self.context,
			thread.id,
			"EMAIL-1",
			"dispatch@hvac.test",
			("customer@example.test",),
			(),
			"Visit confirmed",
			"We will arrive at 2 PM.",
		)
		proposal = self.service.preview_send(self.context, draft.id)
		self.assertEqual(
			self.repository.get_message("HVAC CO", draft.id).delivery_state, DeliveryState.PENDING_APPROVAL
		)
		provider = FakeEmailProvider()
		receipt = self.service.approve_send(
			self.context,
			proposal.id,
			"email:1",
			provider,
			"EMAIL-1",
			"dispatch@hvac.test",
			ActionEngine(),
		)
		self.assertEqual(receipt.result["state"], "sent")
		self.assertEqual(len(provider.sent), 1)
		self.assertEqual(self.repository.get_message("HVAC CO", draft.id).external_id, "provider-123")

	def test_provider_error_is_persisted_for_retry(self):
		thread = self.repository.save_thread(
			CommunicationThread(
				None,
				"HVAC CO",
				"Appointment",
				CommunicationChannel.EMAIL,
				ThreadState.OPEN,
				(CommunicationParticipant("customer@example.test", ParticipantRole.CUSTOMER),),
			)
		)
		draft = self.service.draft(
			self.context,
			thread.id,
			"EMAIL-1",
			"dispatch@hvac.test",
			("customer@example.test",),
			(),
			"Hi",
			"Body",
		)
		proposal = self.service.preview_send(self.context, draft.id)
		with self.assertRaises(RuntimeError):
			self.service.approve_send(
				self.context,
				proposal.id,
				"email:fail",
				FakeEmailProvider(True),
				"EMAIL-1",
				"dispatch@hvac.test",
				ActionEngine(),
			)
		failed = self.repository.get_message("HVAC CO", draft.id)
		self.assertEqual(failed.delivery_state, DeliveryState.FAILED)
		self.assertIn("provider unavailable", failed.error)

	def test_delivery_event_updates_existing_message(self):
		thread = self.repository.save_thread(
			CommunicationThread(None, "HVAC CO", "Test", CommunicationChannel.EMAIL, ThreadState.OPEN, ())
		)
		draft = self.service.draft(
			self.context,
			thread.id,
			"EMAIL-1",
			"dispatch@hvac.test",
			("customer@example.test",),
			(),
			"Hi",
			"Body",
		)
		proposal = self.service.preview_send(self.context, draft.id)
		self.service.approve_send(
			self.context,
			proposal.id,
			"email:2",
			FakeEmailProvider(),
			"EMAIL-1",
			"dispatch@hvac.test",
			ActionEngine(),
		)
		updated = self.service.apply_delivery_event(
			"HVAC CO",
			"EMAIL-1",
			EmailDeliveryEvent("provider-123", DeliveryState.BOUNCED, datetime.now(UTC), "bad mailbox"),
		)
		self.assertEqual(updated.delivery_state, DeliveryState.BOUNCED)
		self.assertEqual(updated.error, "bad mailbox")

	def test_normalized_webhook_rejects_bad_signature(self):
		payload = json.dumps(
			{
				"id": "1",
				"from": {"address": "a@example.test"},
				"received_at": "2026-09-19T14:00:00+00:00",
				"text": "Hello",
			}
		).encode()
		with self.assertRaises(PermissionError):
			FrappeEmailProvider().verify_and_parse_inbound(payload, {"X-Field-OS-Signature": "bad"}, "secret")
		signature = hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
		parsed = FrappeEmailProvider().verify_and_parse_inbound(
			payload, {"X-Field-OS-Signature": f"sha256={signature}"}, "secret"
		)
		self.assertEqual(parsed.external_id, "1")
