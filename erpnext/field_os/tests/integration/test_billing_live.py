"""Real persistence and real Stripe signature verification, deterministic provider fixtures."""

import hashlib
import hmac
import json
import os
import secrets
import time
import unittest
from unittest.mock import MagicMock, patch

import frappe
import stripe

from erpnext.field_os.api import billing as api
from erpnext.field_os.commercial import billing, native
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B, MANAGER
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER, prepare_onboarding


class LiveBilling(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		prepare_onboarding()
		native.migrate_subscriptions()

	def setUp(self):
		frappe.db.savepoint("billing_test")
		frappe.set_user(OWNER)
		self.secret = secrets.token_hex(32)
		self.api = MagicMock()
		self.api.v1.customers.create.return_value = frappe._dict(id="cus_fixture")
		self.api.v1.subscriptions.list.return_value = frappe._dict(data=[], has_more=False)
		self.api.v1.invoices.list.return_value = frappe._dict(data=[])
		self.api.v1.checkout.sessions.create.return_value = frappe._dict(
			id="cs_fixture", url="https://checkout.stripe.com/fixture"
		)
		self.api.v1.checkout.sessions.retrieve.return_value = frappe._dict(
			status="open", url="https://checkout.stripe.com/fixture"
		)
		self.api.v1.billing_portal.sessions.create.return_value = frappe._dict(
			url="https://billing.stripe.com/fixture"
		)
		for mock in (
			patch.object(billing, "client", return_value=self.api),
			patch.object(
				billing,
				"settings",
				return_value=("fixture", {"standard": "price_standard", "pro": "price_pro"}, False),
			),
			patch.dict(os.environ, {"FIELD_OS_STRIPE_WEBHOOK_SECRET": self.secret}),
			patch.dict(frappe.conf, {"host_name": "https://field-os.example.invalid"}),
		):
			mock.start()
			self.addCleanup(mock.stop)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="billing_test")

	def remote(self, status="active"):
		self.api.v1.subscriptions.list.return_value = frappe._dict(
			data=[
				stripe.Subscription.construct_from(
					dict(
						id="sub_fixture",
						customer="cus_fixture",
						livemode=False,
						status=status,
						metadata={"field_os": billing.digest(COMPANY_A, "tenant")},
						items={
							"data": [
								{
									"quantity": 1,
									"price": {"id": "price_standard"},
									"current_period_end": 2000000000,
								}
							]
						},
					),
					"fixture",
				)
			],
			has_more=False,
		)

	def event(self, event_id="evt_fixture", **overrides):
		payload = {
			"id": event_id,
			"object": "event",
			"type": "customer.subscription.updated",
			"created": 1,
			"livemode": False,
			"data": {"object": {"customer": "cus_fixture", "status": "canceled"}},
		}
		payload.update(overrides)
		raw = json.dumps(payload).encode()
		timestamp = str(int(time.time()))
		signature = hmac.new(
			self.secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
		).hexdigest()
		return raw, f"t={timestamp},v1={signature}"

	def test_checkout_reuses_session_and_rejects_duplicate_subscription(self):
		one = api.checkout(COMPANY_A, "standard")
		self.assertEqual(api.checkout(COMPANY_A, "standard"), one)
		self.assertEqual(self.api.v1.checkout.sessions.create.call_count, 1)
		params = self.api.v1.checkout.sessions.create.call_args.args[0]
		self.assertEqual(params["line_items"], [{"price": "price_standard", "quantity": 1}])
		self.assertNotIn("payment_method_types", params)
		self.assertNotIn("trial_period_days", params["subscription_data"])
		self.remote()
		with self.assertRaises(frappe.ValidationError):
			api.checkout(COMPANY_A, "pro")

	def test_signed_duplicate_and_out_of_order_events_use_current_subscription(self):
		api.checkout(COMPANY_A, "standard")
		self.remote()
		raw, signature = self.event()
		self.assertFalse(billing.receive(raw, signature)["duplicate"])
		self.assertEqual(native.subscription(COMPANY_A).status, "active")
		calls = self.api.v1.subscriptions.list.call_count
		self.assertTrue(billing.receive(raw, signature)["duplicate"])
		self.assertEqual(calls, self.api.v1.subscriptions.list.call_count)
		self.assertEqual(frappe.db.count(billing.EVENT, {"company": COMPANY_A}), 1)

	def test_signature_mode_and_unknown_customer_rejections(self):
		raw, signature = self.event()
		with self.assertRaises(frappe.PermissionError):
			billing.receive(raw + b" ", signature)
		raw, signature = self.event(livemode=True)
		with self.assertRaises(frappe.PermissionError):
			billing.receive(raw, signature)
		self.assertTrue(billing.receive(*self.event())["ignored"])
		self.api.v1.subscriptions.list.assert_not_called()

	def test_owner_portal_and_tenant_binding(self):
		api.checkout(COMPANY_A, "standard")
		self.assertEqual(api.portal(COMPANY_A)["url"], "https://billing.stripe.com/fixture")
		with self.assertRaises(frappe.PermissionError):
			api.status(COMPANY_B)
		frappe.set_user(MANAGER)
		with self.assertRaises(PermissionError):
			api.checkout(COMPANY_A, "standard")

	def test_delinquency_recovery_and_invoice_persistence(self):
		api.checkout(COMPANY_A, "standard")
		self.remote("past_due")
		self.api.v1.invoices.list.return_value = frappe._dict(
			data=[
				frappe._dict(
					id="in_fixture",
					customer="cus_fixture",
					livemode=False,
					status="open",
					currency="usd",
					amount_due=5000,
					amount_paid=0,
					hosted_invoice_url="https://invoice.stripe.com/fixture",
					created=10,
				)
			]
		)
		billing.receive(*self.event("evt_past_due"))
		self.assertEqual(native.subscription(COMPANY_A).status, "past_due")
		grace = native.subscription(COMPANY_A).grace_end
		billing.receive(*self.event("evt_repeat"))
		self.assertEqual(native.subscription(COMPANY_A).grace_end, grace)
		self.remote("active")
		self.api.v1.invoices.list.return_value.data[0].update(status="paid", amount_paid=5000)
		api.refresh(COMPANY_A)
		self.assertEqual(native.subscription(COMPANY_A).status, "active")
		self.assertEqual(api.status(COMPANY_A)["invoices"][0]["status"], "paid")


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveBilling)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Billing acceptance failed")
	return {"passed": result.testsRun}
