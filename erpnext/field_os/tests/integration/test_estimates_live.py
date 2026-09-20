"""Real quotations, stock links, queued email and customer approvals on a disposable site."""

import html
import os
import re
import unittest
from datetime import timedelta
from email import message_from_string, policy

import frappe
from frappe.utils import add_days, now_datetime, nowdate

from erpnext.field_os.api import estimates
from erpnext.field_os.estimates.frappe_repository import DECISION, ESTIMATE
from erpnext.field_os.security.authorization import CapabilityDenied
from erpnext.field_os.tests.integration.test_equipment_live import (
	COMPANY_A,
	COMPANY_B,
	MANAGER,
	OTHER,
	TECH,
	prepare,
)


def prepare_estimates():
	customer, site = prepare()
	frappe.set_user("Administrator")
	frappe.in_test = True
	for name in ("field_os_estimate", "field_os_estimate_decision"):
		frappe.reload_doc("field_os", "doctype", name)
	from erpnext.field_os.install import ensure_native_read_permissions

	ensure_native_read_permissions()
	year = nowdate()[:4]
	if not frappe.db.exists("Fiscal Year", year):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": year,
				"year_start_date": f"{year}-01-01",
				"year_end_date": f"{year}-12-31",
			}
		).insert()
	frappe.db.set_value("Customer", customer, "email_id", "customer@example.invalid")
	if not frappe.db.exists("User", "customer@example.invalid"):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": "customer@example.invalid",
				"first_name": "Avery",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert()
	if os.environ.get("FIELD_OS_TEST_PASSWORD"):
		from frappe.utils.password import update_password

		update_password("customer@example.invalid", os.environ["FIELD_OS_TEST_PASSWORD"])
	if not frappe.db.exists("Price List", "FieldOS Selling"):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": "FieldOS Selling",
				"currency": "USD",
				"selling": 1,
				"enabled": 1,
			}
		).insert()
	frappe.db.set_value("Customer", customer, "default_price_list", "FieldOS Selling")
	for code, stocked, rate in (("FieldOS Labor", 0, 125), ("FieldOS Filter", 1, 25)):
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": "Products",
					"stock_uom": "Nos",
					"is_stock_item": stocked,
					"standard_rate": rate,
				}
			).insert()
	if not frappe.db.exists("Email Account", {"email_id": "estimates@example.invalid"}):
		frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_id": "estimates@example.invalid",
				"email_account_name": "FieldOS Test Outgoing",
				"enable_outgoing": 1,
				"smtp_server": "127.0.0.1",
				"smtp_port": 1025,
				"no_smtp_authentication": 1,
				"use_tls": 0,
				"default_outgoing": 1,
				"always_use_account_email_id_as_sender": 1,
			}
		).insert()
	mailbox = frappe.db.get_value(
		"Field OS Email Integration", {"company": COMPANY_A, "mailbox_key": "estimate-test-a"}, "name"
	)
	if not mailbox:
		mailbox = (
			frappe.get_doc(
				{
					"doctype": "Field OS Email Integration",
					"company": COMPANY_A,
					"enabled": 1,
					"provider": "Frappe",
					"mailbox_key": "estimate-test-a",
					"from_address": "estimates@example.invalid",
					"webhook_secret": "estimate-test-only",
				}
			)
			.insert()
			.name
		)
	return customer, mailbox


class LiveEstimates(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer, cls.mailbox = prepare_estimates()

	def setUp(self):
		frappe.set_user(MANAGER)
		frappe.db.savepoint("estimate_test")
		self.values = {
			"recipient": "customer@example.invalid",
			"email_integration": self.mailbox,
			"valid_until": add_days(nowdate(), 14),
			"items": [
				{"item_code": "FieldOS Labor", "qty": 2, "rate": 125},
				{"item_code": "FieldOS Filter", "qty": 1, "rate": 25, "warehouse": "Stores - FIA"},
			],
		}
		self.estimate = estimates.save_estimate(COMPANY_A, self.customer, self.values)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="estimate_test")
		frappe.clear_cache()

	def send(self):
		preview = estimates.preview_send(COMPANY_A, self.estimate["name"])
		return estimates.approve_send(
			COMPANY_A, preview["proposal"]["id"], preview["proposal"]["id"]
		), preview

	def token(self):
		doc = frappe.get_doc(ESTIMATE, self.estimate["name"])
		message = frappe.db.get_value("Email Queue", doc.email_queue, "message")
		text = (
			message_from_string(message, policy=policy.default)
			.get_body(preferencelist=("html",))
			.get_content()
		)
		return html.unescape(re.search(r"fieldos-estimate\?token=([A-Za-z0-9_-]+)", text).group(1))

	def test_real_quote_parts_preview_send_and_durable_retry(self):
		self.assertEqual(self.estimate["total"], 275)
		sent, preview = self.send()
		self.assertEqual(len(preview["shortages"]), 1)
		self.assertEqual(sent["status"], "Sent")
		self.assertEqual(sent["delivery_status"], "Not Sent")
		self.assertEqual(frappe.db.get_value("Quotation", sent["quotation"], "docstatus"), 1)
		from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore

		FrappeCacheProposalStore().delete(COMPANY_A, preview["proposal"]["id"])
		retried = estimates.approve_send(COMPANY_A, preview["proposal"]["id"], preview["proposal"]["id"])
		self.assertEqual(retried["name"], sent["name"])
		self.assertEqual(
			frappe.db.count("Email Queue", {"reference_doctype": ESTIMATE, "reference_name": sent["name"]}), 1
		)

	def test_customer_approval_is_permanent_and_bound_to_version(self):
		self.send()
		token = self.token()
		frappe.set_user("customer@example.invalid")
		decision = estimates.customer_decision(token, "Approved", "Avery Customer", "Please schedule")
		self.assertEqual(decision["status"], "Approved")
		self.assertEqual(
			estimates.customer_decision(token, "Approved", "Avery Customer")["status"], "Approved"
		)
		with self.assertRaises(frappe.ValidationError):
			estimates.customer_decision(token, "Rejected", "Avery Customer")
		frappe.set_user(MANAGER)
		self.assertEqual(len(estimates.get_estimate(COMPANY_A, self.estimate["name"])["decisions"]), 1)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(DECISION, {"field_os_estimate": self.estimate["name"]}).delete()

	def test_customer_approval_requires_authenticated_recipient(self):
		self.send()
		token = self.token()
		for user in ("Guest", MANAGER, OTHER, "Administrator"):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				estimates.customer_decision(token, "Approved", "Customer")
		self.assertEqual(frappe.db.get_value(ESTIMATE, self.estimate["name"], "status"), "Sent")

	def test_stale_preview_and_cross_company_warehouse_are_rejected(self):
		preview = estimates.preview_send(COMPANY_A, self.estimate["name"])
		values = {**self.values, "items": [{"item_code": "FieldOS Labor", "qty": 3, "rate": 125}]}
		estimates.save_estimate(
			COMPANY_A, self.customer, values, self.estimate["name"], self.estimate["version"]
		)
		with self.assertRaises(frappe.ValidationError):
			estimates.approve_send(COMPANY_A, preview["proposal"]["id"], "stale")
		values["items"] = [{"item_code": "FieldOS Filter", "qty": 1, "rate": 25, "warehouse": "Stores - FIB"}]
		with self.assertRaises(frappe.ValidationError):
			estimates.save_estimate(COMPANY_A, self.customer, values)

	def test_role_and_native_tenant_permissions(self):
		frappe.set_user(TECH)
		with self.assertRaises(CapabilityDenied):
			estimates.preview_send(COMPANY_A, self.estimate["name"])
		frappe.set_user(OTHER)
		self.assertFalse(frappe.has_permission(ESTIMATE, "read", doc=self.estimate["name"]))
		self.assertNotIn(self.estimate["name"], frappe.get_list(ESTIMATE, pluck="name"))
		with self.assertRaises(frappe.PermissionError):
			estimates.get_estimate(COMPANY_B, self.estimate["name"])

	def test_invalid_and_expired_customer_tokens(self):
		self.send()
		token = self.token()
		frappe.set_user("Administrator")
		frappe.db.set_value(
			ESTIMATE, self.estimate["name"], "token_expires_at", now_datetime() - timedelta(days=1)
		)
		frappe.set_user("customer@example.invalid")
		for candidate in ("invalid", token):
			with self.assertRaises(frappe.PermissionError):
				estimates.customer_decision(candidate, "Approved", "Customer")

	def test_approval_is_bound_to_actor_and_current_customer_version(self):
		preview = estimates.preview_send(COMPANY_A, self.estimate["name"])
		frappe.set_user("Administrator")
		with self.assertRaises(ValueError):
			estimates.approve_send(COMPANY_A, preview["proposal"]["id"], "wrong-actor")
		frappe.set_user(MANAGER)
		self.send()
		token = self.token()
		frappe.set_user("Administrator")
		frappe.get_doc("Quotation", self.estimate["quotation"]).cancel()
		frappe.set_user("customer@example.invalid")
		with self.assertRaises(frappe.ValidationError):
			estimates.customer_decision(token, "Approved", "Customer")

	def test_ai_prepares_server_totals_and_requires_approval(self):
		from erpnext.field_os.actions.engine import ActionEngine
		from erpnext.field_os.ai.conversation import AskOperationsService, MemoryConversationStore
		from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
		from erpnext.field_os.ai.provider import ModelReply
		from erpnext.field_os.ai.tools import ToolRegistry
		from erpnext.field_os.estimates.ai import register
		from erpnext.field_os.security.context import resolve_tenant_context

		name = self.estimate["name"]

		class Provider:
			def respond(self, messages, tools):
				return ModelReply(
					"Review the estimate",
					{"tool": "send_estimate", "arguments": {"estimate_id": name, "total": 1}},
				)

		registry = ToolRegistry()
		register(registry)
		service = AskOperationsService(
			Provider(), registry, MemoryConversationStore(), FrappeCacheProposalStore()
		)
		context = resolve_tenant_context(COMPANY_A)
		result = service.ask(context, "Send this estimate")
		self.assertEqual(result.approval.arguments["total"], 275)
		self.assertEqual(
			frappe.db.count("Email Queue", {"reference_doctype": ESTIMATE, "reference_name": name}), 0
		)
		service.approve(context, result.approval.proposal_id, "ai-approved-send", ActionEngine())
		self.assertEqual(
			frappe.db.count("Email Queue", {"reference_doctype": ESTIMATE, "reference_name": name}), 1
		)


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveEstimates)
	)
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise RuntimeError("Estimate acceptance failed")
	return {"passed": result.testsRun}


def deliver_browser_estimate(estimate_id):
	"""Deliver only the disposable browser fixture to its local SMTP capture server."""
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	doc = frappe.get_doc(ESTIMATE, estimate_id)
	if doc.company != COMPANY_A or doc.recipient != "customer@example.invalid":
		raise RuntimeError("Only browser fixture estimates may be delivered")
	account = frappe.get_doc("Email Account", {"email_id": "estimates@example.invalid"})
	if account.smtp_server != "127.0.0.1" or int(account.smtp_port) != 1025:
		raise RuntimeError("Browser acceptance requires the local SMTP capture server")
	frappe.get_doc("Email Queue", doc.email_queue).send()
	from erpnext.field_os.estimates.workflow import sync_delivery

	sync_delivery()
	return {"delivered": doc.name}
