from datetime import UTC, datetime
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.communications.email import DeterministicEmailClassifier
from erpnext.field_os.communications.models import (
	CommunicationChannel,
	CommunicationParticipant,
	CommunicationThread,
	ConsentState,
	DeliveryState,
	EntityLinks,
	ParticipantRole,
	ThreadState,
)
from erpnext.field_os.communications.sms import (
	InboundSMS,
	SMSDeliveryEvent,
	SMSSendResult,
	SMSService,
	SMSTemplate,
	render_sms_template,
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
	def resolve(self, company, sender_number):
		return EntityLinks(customer_id="CUST-1") if sender_number == "+14045551000" else EntityLinks()


class FakeSMSProvider:
	def __init__(self):
		self.sent = []

	def send(self, sms):
		self.sent.append(sms)
		return SMSSendResult("sms-provider-1", DeliveryState.SENT, datetime.now(UTC))


class TestSMSWorkflow(TestCase):
	def setUp(self):
		self.repository = MemoryCommunicationRepository()
		self.proposals = FakeProposalStore()
		self.service = SMSService(
			self.repository,
			DeterministicEmailClassifier(),
			FakeResolver(),
			self.proposals,
		)
		self.context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))

	def inbound(self, body, message_id="sms-1"):
		return self.service.receive(
			"HVAC CO",
			"SMS-INT-1",
			InboundSMS(
				message_id,
				"+1 (404) 555-1000",
				"+14045559999",
				body,
				datetime(2026, 9, 19, 14, tzinfo=UTC),
			),
		)

	def test_stop_is_recorded_before_thread_ingest_and_blocks_all_send(self):
		result = self.inbound("STOP")
		self.assertEqual(result.consent_state, ConsentState.OPTED_OUT)
		self.assertTrue(result.ingest.created)
		preference = self.repository.get_preference("HVAC CO", CommunicationChannel.SMS, "+14045551000")
		self.assertEqual(preference.state, ConsentState.OPTED_OUT)
		self.assertFalse(
			self.service.communications.can_send(
				"HVAC CO", "+14045551000", CommunicationChannel.SMS, transactional=True
			)
		)

	def test_start_restores_opt_in(self):
		self.inbound("STOP", "sms-stop")
		result = self.inbound("START", "sms-start")
		self.assertEqual(result.consent_state, ConsentState.OPTED_IN)
		self.assertTrue(
			self.service.communications.can_send(
				"HVAC CO", "+14045551000", CommunicationChannel.SMS, transactional=False
			)
		)

	def test_template_renderer_requires_exact_variables(self):
		template = SMSTemplate(
			"TPL-1", "Hi {{name}}, arrival is {{time}}.", frozenset({"name", "time"}), True
		)
		self.assertEqual(
			render_sms_template(template, {"name": "Alex", "time": "2 PM"}),
			"Hi Alex, arrival is 2 PM.",
		)
		with self.assertRaises(ValueError):
			render_sms_template(template, {"name": "Alex"})

	def test_transactional_draft_is_approved_sent_and_delivery_updated(self):
		thread = self.repository.save_thread(
			CommunicationThread(
				None,
				"HVAC CO",
				"SMS",
				CommunicationChannel.SMS,
				ThreadState.OPEN,
				(CommunicationParticipant("+14045551000", ParticipantRole.CUSTOMER),),
			)
		)
		draft = self.service.draft(
			self.context,
			thread.id,
			"SMS-INT-1",
			"+14045559999",
			"+14045551000",
			"Your technician arrives at 2 PM.",
			transactional=True,
		)
		proposal = self.service.preview_send(self.context, draft.id)
		provider = FakeSMSProvider()
		receipt = self.service.approve_send(
			self.context,
			proposal.id,
			"sms:1",
			provider,
			"SMS-INT-1",
			"+14045559999",
			ActionEngine(),
		)
		self.assertEqual(receipt.result["state"], "sent")
		self.assertEqual(provider.sent[0].to_number, "+14045551000")
		updated = self.service.apply_delivery_event(
			"HVAC CO",
			"SMS-INT-1",
			SMSDeliveryEvent("sms-provider-1", DeliveryState.DELIVERED, datetime.now(UTC)),
		)
		self.assertEqual(updated.delivery_state, DeliveryState.DELIVERED)

	def test_stop_after_preview_blocks_approval(self):
		thread = self.repository.save_thread(
			CommunicationThread(None, "HVAC CO", "SMS", CommunicationChannel.SMS, ThreadState.OPEN, ())
		)
		draft = self.service.draft(
			self.context,
			thread.id,
			"SMS-INT-1",
			"+14045559999",
			"+14045551000",
			"Appointment reminder",
			transactional=True,
		)
		proposal = self.service.preview_send(self.context, draft.id)
		self.inbound("STOP", "sms-stop-after-preview")
		with self.assertRaises(PermissionError):
			self.service.approve_send(
				self.context,
				proposal.id,
				"sms:blocked",
				FakeSMSProvider(),
				"SMS-INT-1",
				"+14045559999",
				ActionEngine(),
			)
