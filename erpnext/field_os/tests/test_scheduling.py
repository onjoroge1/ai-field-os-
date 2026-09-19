from datetime import UTC, datetime
from unittest import TestCase

from erpnext.field_os.domain.scheduling import (
	BusyWindow,
	ScheduleRequest,
	Technician,
	propose_technicians,
)
from erpnext.field_os.domain.service_request import RequestStatus, ServiceRequest


class TestScheduling(TestCase):
	def test_filters_skill_and_conflicts_deterministically(self):
		start = datetime(2026, 9, 21, 14, tzinfo=UTC)
		end = datetime(2026, 9, 21, 16, tzinfo=UTC)
		techs = [
			Technician("T2", "Mike", frozenset({"commercial-hvac"})),
			Technician("T1", "Sarah", frozenset({"commercial-hvac", "rooftop"})),
		]
		busy = [BusyWindow("T2", start, end)]
		result = propose_technicians(ScheduleRequest(start, end, frozenset({"commercial-hvac"})), techs, busy)
		self.assertEqual([item.technician_id for item in result], ["T1"])

	def test_request_lifecycle_rejects_skips(self):
		request = ServiceRequest("R1", "HVAC CO", "C1", "S1", "No cooling")
		with self.assertRaises(ValueError):
			request.transition(RequestStatus.BOOKED)
		self.assertEqual(request.transition(RequestStatus.TRIAGED).status, RequestStatus.TRIAGED)
