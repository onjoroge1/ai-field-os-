from datetime import UTC, datetime, timedelta
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine, ActionRejected
from erpnext.field_os.domain.scheduling import ScheduleRequest, Technician
from erpnext.field_os.domain.service_request import ServiceRequest
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole
from erpnext.field_os.workflows.request_to_booking import RequestToBookingWorkflow


class TestRequestToBooking(TestCase):
	def setUp(self):
		self.context = TenantContext("HVAC CO", "dispatcher@example.test", frozenset({FieldOSRole.DISPATCHER}))
		self.request = ServiceRequest("R1", "HVAC CO", "C1", "SITE1", "RTU not cooling")
		start = datetime.now(UTC) + timedelta(days=1)
		self.schedule = ScheduleRequest(start, start + timedelta(hours=2), frozenset({"commercial-hvac"}))
		self.techs = [Technician("T1", "Sarah", frozenset({"commercial-hvac"}))]
		self.workflow = RequestToBookingWorkflow()

	def test_full_plan_requires_human_approval_before_side_effects(self):
		plan = self.workflow.plan(self.context, self.request, self.schedule, self.techs, [])
		created = []
		sent = []
		with self.assertRaises(ActionRejected):
			ActionEngine().execute(plan.proposal, "booking:R1", lambda: created.append("JOB-1"))
		self.assertEqual(created, [])
		self.assertEqual(sent, [])

	def test_approved_booking_creates_job_and_confirmation_once(self):
		plan = self.workflow.plan(self.context, self.request, self.schedule, self.techs, [])
		created = []
		sent = []
		engine = ActionEngine()

		def create_job(_plan):
			created.append("JOB-1")
			return "JOB-1"

		def send_confirmation(_plan, job_id):
			sent.append(job_id)

		first = self.workflow.approve_and_book(
			self.context, plan, "manager@example.test", create_job, send_confirmation, engine, "booking:R1"
		)
		second = self.workflow.approve_and_book(
			self.context, plan, "manager@example.test", create_job, send_confirmation, engine, "booking:R1"
		)
		self.assertEqual(first, second)
		self.assertEqual(created, ["JOB-1"])
		self.assertEqual(sent, ["JOB-1"])

	def test_cross_tenant_request_is_rejected(self):
		request = ServiceRequest("R2", "OTHER CO", "C1", "S1", "No cooling")
		with self.assertRaises(PermissionError):
			self.workflow.plan(self.context, request, self.schedule, self.techs, [])
