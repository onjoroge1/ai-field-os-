"""Real outbox persistence, worker commits, retries and tenant replay boundaries.

Worker entrypoints commit their own durable boundaries. Fixture cleanup belongs
to the outer bench command transaction, keeping test helpers free of manual commits.
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.communications.email import (
	DeterministicEmailClassifier,
	EmailSendResult,
	EmailService,
	InboundEmail,
)
from erpnext.field_os.communications.models import DeliveryState, EntityLinks
from erpnext.field_os.jobs import service
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER, prepare_onboarding
from erpnext.field_os.tests.test_sms import FakeProposalStore


class LiveJobs(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		prepare_onboarding()

	def setUp(self):
		frappe.set_user("Administrator")
		self.jobs = []
		self.threads = []

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		for name in self.jobs:
			frappe.db.delete(service.JOB, {"name": name})
		for thread in self.threads:
			frappe.db.delete("Field OS Communication Message", {"thread": thread})
			frappe.db.delete("Field OS Communication Thread", {"name": thread})

	def job(self):
		doc = service.admit(COMPANY_A, "email.poll", "fixture:" + uuid4().hex, actor=OWNER)
		self.jobs.append(doc.name)
		return doc

	def test_durable_admission_and_duplicate_worker_delivery(self):
		doc = self.job()
		self.assertEqual(service.admit(COMPANY_A, doc.kind, doc.source, actor=OWNER).name, doc.name)
		with patch.object(service, "poll") as poll:
			service.run(doc.name)
			service.run(doc.name)
			poll.assert_called_once()
		doc.reload()
		self.assertEqual((doc.status, doc.attempts), ("Succeeded", 1))

	def test_approved_email_is_queued_then_dispatched_once(self):
		repo = service.FrappeCommunicationRepository()
		workflow = EmailService(
			repo,
			DeterministicEmailClassifier(),
			SimpleNamespace(resolve=lambda *a: EntityLinks()),
			FakeProposalStore(),
		)
		inbound = workflow.receive(
			COMPANY_A,
			"queue-test",
			InboundEmail(
				uuid4().hex,
				uuid4().hex,
				"customer@example.test",
				None,
				("office@example.test",),
				(),
				"Service",
				"Need repair",
				datetime.now(UTC),
			),
		)
		self.threads.append(inbound.thread.id)
		frappe.set_user(OWNER)
		context = service.resolve_tenant_context(COMPANY_A)
		draft = workflow.draft(
			context,
			inbound.thread.id,
			"queue-test",
			"office@example.test",
			("customer@example.test",),
			(),
			"Reply",
			"Approved response",
		)
		proposal = workflow.preview_send(context, draft.id)
		workflow.approve_send(
			context,
			proposal.id,
			uuid4().hex,
			service.DurableSender(context, "email", "queue-test"),
			"queue-test",
			"office@example.test",
			ActionEngine(),
		)
		name = frappe.db.get_value(service.JOB, {"company": COMPANY_A, "source": draft.id}, "name")
		self.jobs.append(name)
		self.assertEqual(repo.get_message(COMPANY_A, draft.id).delivery_state, DeliveryState.QUEUED)
		frappe.set_user("Administrator")
		with patch.object(service, "load_email_integration") as load:
			provider = unittest.mock.Mock(supports_idempotency=True)
			provider.send.return_value = EmailSendResult(
				"receipt-" + uuid4().hex, DeliveryState.SENT, datetime.now(UTC)
			)
			load.return_value = SimpleNamespace(
				company=COMPANY_A, from_address="office@example.test", provider=provider
			)
			service.run(name)
			service.run(name)
			provider.send.assert_called_once()
		self.assertEqual(repo.get_message(COMPANY_A, draft.id).delivery_state, DeliveryState.SENT)
		self.assertEqual(frappe.db.get_value(service.JOB, name, "status"), "Succeeded")

	def test_retry_dead_letter_and_expired_ambiguous_lease(self):
		doc = self.job()
		with patch.object(service, "poll", side_effect=ConnectionError("secret-provider-body")):
			service.run(doc.name)
		doc.reload()
		self.assertEqual((doc.status, doc.error_code), ("Retry", "poll_failed"))
		self.assertNotIn("secret", doc.as_json())
		frappe.db.set_value(
			service.JOB,
			doc.name,
			{
				"status": "Running",
				"dispatched": 1,
				"replay_safe": 0,
				"lease_until": now_datetime() - timedelta(seconds=1),
			},
		)
		with patch.object(frappe, "enqueue"):
			service.tick()
		doc.reload()
		self.assertEqual(doc.status, "Uncertain")

	def test_reconciliation_requires_tenant_and_explicit_outcome(self):
		doc = self.job()
		frappe.db.set_value(service.JOB, doc.name, "status", "Uncertain")
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.PermissionError):
			service.replay(COMPANY_B, doc.name, "Provider log checked")
		with self.assertRaises(ValueError):
			service.replay(COMPANY_A, doc.name, "Provider log checked")
		service.replay(COMPANY_A, doc.name, "Provider confirms no delivery", "confirmed_not_sent")
		self.assertEqual(frappe.db.get_value(service.JOB, doc.name, "status"), "Queued")


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveJobs)
	)
	if not result.wasSuccessful():
		raise AssertionError("Durable jobs acceptance failed")
	return {"passed": result.testsRun}
