"""Assigned technician evidence → native stock and accounting → approved invoice delivery."""

import base64
import io
import os
import unittest

import frappe
from frappe.utils import add_days, getdate, nowdate
from PIL import Image, ImageDraw

from erpnext.field_os.agreements.service import add_months
from erpnext.field_os.api import agreements, completions
from erpnext.field_os.completions.repository import CHECKS, COMPLETION, NOTICE
from erpnext.field_os.security.authorization import CapabilityDenied
from erpnext.field_os.tests.integration.test_agreements_live import TECHNICIAN, prepare_agreements
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B, MANAGER, OTHER, TECH

BILLING = "fieldos-billing@example.invalid"
UNASSIGNED = "fieldos-unassigned@example.invalid"


def image_data(signature=False):
	picture = Image.new("RGB", (200, 80), "white" if signature else "steelblue")
	ImageDraw.Draw(picture).line([(10, 65), (45, 12), (70, 55), (170, 24)], fill="black", width=4)
	buffer = io.BytesIO()
	picture.save(buffer, "PNG")
	return base64.b64encode(buffer.getvalue()).decode()


def prepare_completions():
	customer, site = prepare_agreements()
	for name in ("field_os_work_completion", "field_os_invoice_notice"):
		frappe.reload_doc("field_os", "doctype", name)
	for user, role in ((BILLING, "Field OS Billing"), (UNASSIGNED, "Field OS Technician")):
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": user.split("@")[0],
					"send_welcome_email": 0,
					"user_type": "System User",
					"roles": [{"role": role}],
				}
			).insert()
		if not frappe.db.exists(
			"User Permission", {"user": user, "allow": "Company", "for_value": COMPANY_A}
		):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": user,
					"allow": "Company",
					"for_value": COMPANY_A,
					"apply_to_all_doctypes": 1,
				}
			).insert()
		frappe.defaults.set_user_default("company", COMPANY_A, user)
		if os.environ.get("FIELD_OS_TEST_PASSWORD"):
			from frappe.utils.password import update_password

			update_password(user, os.environ["FIELD_OS_TEST_PASSWORD"])
	liability = frappe.db.get_value(
		"Account", {"company": COMPANY_A, "root_type": "Liability", "is_group": 1}, "name"
	)
	tax_account = frappe.db.get_value(
		"Account", {"company": COMPANY_A, "account_name": "FieldOS Service Tax"}, "name"
	)
	if not tax_account:
		tax_account = (
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": "FieldOS Service Tax",
					"company": COMPANY_A,
					"parent_account": liability,
					"account_type": "Tax",
				}
			)
			.insert()
			.name
		)
	tax = frappe.db.get_value(
		"Sales Taxes and Charges Template", {"company": COMPANY_A, "title": "FieldOS Service Tax 10%"}, "name"
	)
	if not tax:
		tax = (
			frappe.get_doc(
				{
					"doctype": "Sales Taxes and Charges Template",
					"title": "FieldOS Service Tax 10%",
					"company": COMPANY_A,
					"taxes": [
						{
							"charge_type": "On Net Total",
							"account_head": tax_account,
							"rate": 10,
							"description": "Service tax",
						}
					],
				}
			)
			.insert()
			.name
		)
	quantity = (
		frappe.db.get_value("Bin", {"item_code": "FieldOS Filter", "warehouse": "Stores - FIA"}, "actual_qty")
		or 0
	)
	if quantity < 10:
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": COMPANY_A,
				"stock_entry_type": "Material Receipt",
				"posting_date": nowdate(),
				"items": [
					{
						"item_code": "FieldOS Filter",
						"qty": 20,
						"basic_rate": 20,
						"t_warehouse": "Stores - FIA",
					}
				],
			}
		)
		entry.insert()
		entry.submit()
	return customer, site, tax


def make_job(customer, site, scheduled=None):
	frappe.set_user(MANAGER)
	agreement = agreements.save_agreement(
		COMPANY_A,
		customer,
		site,
		{
			"starts_on": add_months(getdate(), -4).isoformat(),
			"ends_on": add_months(getdate(), 8).isoformat(),
			"interval_months": 3,
			"renewal_notice_days": 30,
			"service_item": "FieldOS Labor",
		},
	)
	agreement = agreements.set_status(COMPANY_A, agreement["name"], "Active", agreement["modified"])
	return agreements.schedule_visit(
		COMPANY_A, agreement["visits"][0].name, TECHNICIAN, scheduled or nowdate() + " 09:00:00"
	)["job"]


def fill_completion(job):
	frappe.set_user(TECH)
	work = completions.start_completion(COMPANY_A, job)
	photo = completions.upload_evidence(COMPANY_A, work["name"], image_data())["file_url"]
	signature = completions.upload_evidence(COMPANY_A, work["name"], image_data(True), "Signature")[
		"file_url"
	]
	return completions.save_completion(
		COMPANY_A,
		work["name"],
		{
			"summary": "Replaced filter and verified heating operation",
			"checklist": dict.fromkeys(CHECKS, True),
			"photos": [photo],
			"signature": signature,
			"signer_name": "Avery Customer",
			"billables": [
				{"item_code": "FieldOS Labor", "qty": 1, "rate": 100},
				{"item_code": "FieldOS Filter", "qty": 1, "rate": 20, "warehouse": "Stores - FIA"},
			],
		},
		work["version"],
	)


class LiveCompletions(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer, cls.site, cls.tax = prepare_completions()

	def setUp(self):
		frappe.db.savepoint("completion_test")
		self.job = make_job(self.customer, self.site)
		frappe.set_user(TECH)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="completion_test")
		frappe.clear_cache()

	def finish(self):
		work = fill_completion(self.job)
		return completions.complete(COMPANY_A, work["name"], work["version"])

	def post(self):
		work = self.finish()
		frappe.set_user(BILLING)
		preview = completions.preview_invoice(COMPANY_A, work["name"], add_days(nowdate(), 30), self.tax)
		return completions.approve_invoice(COMPANY_A, preview["proposal"]["id"], "post-once")

	def test_required_evidence_native_completion_and_immutable_private_files(self):
		work = completions.start_completion(COMPANY_A, self.job)
		with self.assertRaises(frappe.ValidationError):
			completions.complete(COMPANY_A, work["name"], work["version"])
		work = self.finish()
		self.assertEqual(work["status"], "Completed")
		self.assertEqual(frappe.db.get_value("Maintenance Visit", self.job, "docstatus"), 1)
		with self.assertRaises(frappe.ValidationError):
			completions.save_completion(COMPANY_A, work["name"], {"summary": "rewrite"}, work["version"])
		file = frappe.get_doc("File", {"file_url": work["signature"]})
		self.assertTrue(file.is_downloadable())
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			file.delete()
		doc = frappe.get_doc(COMPLETION, work["name"])
		doc.summary = "rewrite"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_assignment_tenant_native_read_and_stale_write_boundaries(self):
		work = fill_completion(self.job)
		with self.assertRaises(frappe.TimestampMismatchError):
			completions.save_completion(COMPANY_A, work["name"], {}, "stale")
		for user, company in ((UNASSIGNED, COMPANY_A), (OTHER, COMPANY_B)):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				completions.get_completion(company, work["name"])
			self.assertNotIn(work["name"], frappe.get_list(COMPLETION, pluck="name"))
			self.assertFalse(frappe.get_doc("File", {"file_url": work["signature"]}).is_downloadable())
		frappe.set_user(TECH)
		with self.assertRaises(CapabilityDenied):
			completions.preview_invoice(COMPANY_A, work["name"], nowdate())
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(COMPLETION, work["name"]).save()

	def test_invoice_preview_has_no_posting_and_approval_posts_native_gl_and_stock_once(self):
		work = self.finish()
		frappe.set_user(BILLING)
		before = frappe.db.get_value(
			"Bin", {"item_code": "FieldOS Filter", "warehouse": "Stores - FIA"}, "actual_qty"
		)
		preview = completions.preview_invoice(COMPANY_A, work["name"], add_days(nowdate(), 30), self.tax)
		self.assertEqual(preview["total"], 132)
		self.assertEqual(frappe.db.get_value("Sales Invoice", preview["invoice"], "docstatus"), 0)
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": preview["invoice"]}))
		posted = completions.approve_invoice(COMPANY_A, preview["proposal"]["id"], "post-once")
		self.assertEqual(posted["financials"].grand_total, 132)
		entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": posted["invoice"], "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		self.assertAlmostEqual(sum(x.debit for x in entries), 132)
		self.assertAlmostEqual(sum(x.credit for x in entries), 132)
		self.assertEqual(
			frappe.db.get_value(
				"Bin", {"item_code": "FieldOS Filter", "warehouse": "Stores - FIA"}, "actual_qty"
			),
			before - 1,
		)
		frappe.cache.flushdb()
		retried = completions.approve_invoice(COMPANY_A, preview["proposal"]["id"], "post-once")
		self.assertEqual(retried["invoice"], posted["invoice"])

	def test_modified_invoice_cannot_use_old_financial_approval(self):
		work = self.finish()
		frappe.set_user(BILLING)
		preview = completions.preview_invoice(COMPANY_A, work["name"], nowdate())
		frappe.set_user("Administrator")
		invoice = frappe.get_doc("Sales Invoice", preview["invoice"])
		invoice.items[0].rate += 1
		invoice.save()
		frappe.set_user(BILLING)
		with self.assertRaises(frappe.ValidationError):
			completions.approve_invoice(COMPANY_A, preview["proposal"]["id"], "stale")
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 0)

	def test_notice_is_explicit_durable_and_paid_followup_is_blocked(self):
		work = self.post()
		mailbox = frappe.db.get_value(
			"Field OS Email Integration", {"company": COMPANY_A, "mailbox_key": "estimate-test-a"}, "name"
		)
		self.assertFalse(frappe.db.exists(NOTICE, {"completion": work["name"]}))
		preview = completions.preview_notice(COMPANY_A, work["name"], "customer@example.invalid", mailbox)
		sent = completions.approve_notice(COMPANY_A, preview["proposal"]["id"], "mail-once")
		self.assertEqual(len(sent["notices"]), 1)
		self.assertEqual(sent["notices"][0].delivery_status, "Not Sent")
		frappe.cache.flushdb()
		self.assertEqual(
			len(completions.approve_notice(COMPANY_A, preview["proposal"]["id"], "mail-once")["notices"]), 1
		)
		followup = completions.preview_notice(
			COMPANY_A, work["name"], "customer@example.invalid", mailbox, "Follow-up"
		)
		frappe.set_user("Administrator")
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		payment = get_payment_entry(
			"Sales Invoice",
			work["invoice"],
			bank_account=frappe.db.get_value("Company", COMPANY_A, "default_cash_account"),
		)
		payment.reference_no, payment.reference_date = "acceptance-payment", nowdate()
		payment.insert()
		payment.submit()
		self.assertEqual(frappe.db.get_value("Sales Invoice", work["invoice"], "outstanding_amount"), 0)
		frappe.set_user(BILLING)
		with self.assertRaises(frappe.ValidationError):
			completions.approve_notice(COMPANY_A, followup["proposal"]["id"], "paid-followup")
		with self.assertRaises(frappe.ValidationError):
			completions.preview_notice(
				COMPANY_A, work["name"], "customer@example.invalid", mailbox, "Follow-up"
			)


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveCompletions)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Completion live acceptance checks failed")
	return {"passed": result.testsRun}
