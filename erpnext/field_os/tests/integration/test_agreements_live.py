"""Actual contract persistence, recurring visits, native dispatch and renewal isolation."""

import unittest

import frappe
from frappe.utils import add_days, getdate, nowdate

from erpnext.field_os.agreements.frappe_repository import AGREEMENT, VISIT, expire_agreements
from erpnext.field_os.agreements.service import add_months
from erpnext.field_os.api import agreements
from erpnext.field_os.dispatch.frappe_repository import FrappeDispatchRepository
from erpnext.field_os.security.authorization import CapabilityDenied
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B, MANAGER, OTHER, TECH
from erpnext.field_os.tests.integration.test_estimates_live import prepare_estimates

TECHNICIAN = "FieldOS Agreement Technician"


def prepare_agreements():
	customer, _ = prepare_estimates()
	for name in ("field_os_maintenance_agreement", "field_os_agreement_visit"):
		frappe.reload_doc("field_os", "doctype", name)
	if not frappe.db.exists("Gender", "Male"):
		frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
	employee = frappe.db.get_value("Employee", {"user_id": TECH, "company": COMPANY_A}, "name")
	if not employee:
		employee = (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Avery Technician",
					"company": COMPANY_A,
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"status": "Active",
					"user_id": TECH,
				}
			)
			.insert()
			.name
		)
	if not frappe.db.exists("Sales Person", TECHNICIAN):
		frappe.get_doc(
			{
				"doctype": "Sales Person",
				"sales_person_name": TECHNICIAN,
				"employee": employee,
				"enabled": 1,
				"is_group": 0,
			}
		).insert()
	return customer, frappe.db.get_value("Address", {"address_title": "FieldOS Service Site"}, "name")


class LiveAgreements(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer, cls.site = prepare_agreements()

	def setUp(self):
		frappe.set_user(MANAGER)
		frappe.db.savepoint("agreement_test")
		self.values = {
			"starts_on": add_months(getdate(), -7).isoformat(),
			"ends_on": add_months(getdate(), 5).isoformat(),
			"interval_months": 3,
			"renewal_notice_days": 180,
			"service_item": "FieldOS Labor",
		}
		self.agreement = agreements.save_agreement(COMPANY_A, self.customer, self.site, self.values)

	def tearDown(self):
		super().tearDown()
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="agreement_test")
		frappe.clear_cache()

	def activate(self):
		self.agreement = agreements.set_status(
			COMPANY_A, self.agreement["name"], "Active", self.agreement["modified"]
		)
		return self.agreement

	def test_activation_creates_fixed_cadence_and_resume_does_not_duplicate(self):
		active = self.activate()
		self.assertEqual(len(active["visits"]), 4)
		self.assertEqual(
			[getdate(v.due_on) for v in active["visits"]],
			[add_months(getdate(self.values["starts_on"]), n) for n in (3, 6, 9, 12)],
		)
		dashboard = agreements.dashboard(COMPANY_A)
		self.assertEqual(dashboard["counts"]["overdue"], 2)
		paused = agreements.set_status(COMPANY_A, active["name"], "Paused", active["modified"])
		resumed = agreements.set_status(COMPANY_A, active["name"], "Active", paused["modified"])
		self.assertEqual([v.name for v in active["visits"]], [v.name for v in resumed["visits"]])

	def test_schedule_creates_one_native_dispatch_job_and_completion_updates_dashboard(self):
		active = self.activate()
		visit = active["visits"][0]
		job = agreements.schedule_visit(COMPANY_A, visit.name, TECHNICIAN, nowdate() + " 09:00:00")["job"]
		self.assertEqual(
			agreements.schedule_visit(COMPANY_A, visit.name, TECHNICIAN, nowdate() + " 09:00:00")["job"], job
		)
		native = FrappeDispatchRepository().get_job(COMPANY_A, job)
		self.assertEqual(native.technician_id, TECHNICIAN)
		self.assertEqual(native.customer_id, self.customer)
		self.assertEqual(native.status, "Scheduled")
		updated = FrappeDispatchRepository().update_assignment(
			COMPANY_A, job, TECHNICIAN, native.start, native.end, native.version
		)
		self.assertEqual(updated.id, job)
		with self.assertRaises(ValueError):
			agreements.schedule_visit(
				COMPANY_A, active["visits"][1].name, TECHNICIAN, nowdate() + " 09:00:00"
			)
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Maintenance Visit", job)
		doc.completion_status = "Fully Completed"
		doc.purposes[0].work_done = "Performed filter inspection and electrical checks"
		doc.submit()
		frappe.set_user(MANAGER)
		updated = agreements.get_agreement(COMPANY_A, active["name"])
		self.assertEqual(updated["visits"][0].state, "Completed")
		self.assertEqual(updated["visits"][1].due_on, active["visits"][1].due_on)

	def test_renewal_is_a_separate_draft_and_retries_return_same_contract(self):
		active = self.activate()
		end = add_months(getdate(active["ends_on"]), 12).isoformat()
		renewal = agreements.renew(COMPANY_A, active["name"], end, active["modified"])
		self.assertEqual(renewal["status"], "Draft")
		self.assertEqual(getdate(renewal["starts_on"]), getdate(add_days(active["ends_on"], 1)))
		self.assertEqual(
			agreements.renew(COMPANY_A, active["name"], end, active["modified"])["name"], renewal["name"]
		)
		self.assertEqual(agreements.dashboard(COMPANY_A)["counts"]["renewals"], 0)
		self.assertEqual(frappe.db.get_value(AGREEMENT, active["name"], "status"), "Active")

	def test_roles_company_boundaries_and_native_permissions(self):
		self.activate()
		frappe.set_user(TECH)
		self.assertEqual(
			agreements.get_agreement(COMPANY_A, self.agreement["name"])["name"], self.agreement["name"]
		)
		with self.assertRaises(CapabilityDenied):
			agreements.set_status(COMPANY_A, self.agreement["name"], "Paused", self.agreement["modified"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(AGREEMENT, self.agreement["name"]).save()
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			agreements.get_agreement(COMPANY_B, self.agreement["name"])
		self.assertNotIn(self.agreement["name"], frappe.get_list(AGREEMENT, pluck="name"))
		self.assertEqual(frappe.get_list(VISIT, pluck="name"), [])

	def test_stale_draft_invalid_site_and_active_terms_are_rejected(self):
		with self.assertRaises(frappe.TimestampMismatchError):
			agreements.set_status(COMPANY_A, self.agreement["name"], "Active", "2000-01-01")
		with self.assertRaises(frappe.ValidationError):
			agreements.save_agreement(COMPANY_A, self.customer, "missing", self.values)
		self.activate()
		with self.assertRaises(frappe.ValidationError):
			agreements.save_agreement(
				COMPANY_A,
				self.customer,
				self.site,
				{**self.values, "interval_months": 1},
				self.agreement["name"],
				self.agreement["modified"],
			)

	def test_expiry_keeps_unfulfilled_obligations_and_blocks_reactivation(self):
		active = self.activate()
		frappe.set_user("Administrator")
		frappe.db.set_value(AGREEMENT, active["name"], "ends_on", add_days(nowdate(), -1))
		expire_agreements()
		frappe.set_user(MANAGER)
		expired = agreements.get_agreement(COMPANY_A, active["name"])
		self.assertEqual(expired["status"], "Expired")
		self.assertEqual(len(expired["visits"]), 4)
		with self.assertRaises(frappe.ValidationError):
			agreements.set_status(COMPANY_A, active["name"], "Active", expired["modified"])


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveAgreements)
	)
	frappe.set_user("Administrator")
	frappe.db.rollback()
	if not result.wasSuccessful():
		raise AssertionError("Agreement live acceptance checks failed")
	return {"passed": result.testsRun}
