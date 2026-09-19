from datetime import UTC, datetime, timedelta
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.dispatch.models import DispatchJob, TechnicianStatus
from erpnext.field_os.dispatch.service import DispatchService
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class FakeProposalStore:
	def __init__(self):
		self.items = {}

	def save(self, proposal):
		self.items[(proposal.company, proposal.id)] = proposal

	def load(self, company, proposal_id):
		return self.items.get((company, proposal_id))

	def delete(self, company, proposal_id):
		self.items.pop((company, proposal_id), None)


class FakeDispatchRepository:
	def __init__(self, jobs):
		self.jobs = {job.id: job for job in jobs}

	def list_jobs(self, company, start, end):
		return [
			job
			for job in self.jobs.values()
			if job.company == company and job.start < end and job.end > start
		]

	def list_technicians(self, company):
		return [TechnicianStatus("T1", "Sarah", "available", "tech@example.test")]

	def get_job(self, company, job_id):
		job = self.jobs[job_id]
		if job.company != company:
			raise ValueError("not found")
		return job

	def update_assignment(self, company, job_id, technician_id, start, end, expected_version):
		job = self.get_job(company, job_id)
		if expected_version != job.version:
			raise ValueError("stale")
		updated = DispatchJob(
			job.id,
			company,
			job.customer_id,
			job.customer_name,
			job.site_id,
			job.summary,
			job.status,
			start,
			end,
			technician_id,
			"Sarah",
			"tech@example.test",
			"v2",
		)
		self.jobs[job_id] = updated
		return updated


class TestDispatchService(TestCase):
	def setUp(self):
		self.start = datetime(2026, 9, 19, 13, tzinfo=UTC)
		self.job = DispatchJob(
			"JOB-1",
			"HVAC CO",
			"C1",
			"Acme",
			"SITE-1",
			"No cooling",
			"Scheduled",
			self.start,
			self.start + timedelta(hours=2),
			"T1",
			"Sarah",
			"tech@example.test",
			"v1",
		)
		self.dispatcher = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))

	def test_board_detects_overlapping_technician_jobs(self):
		other = DispatchJob(
			"JOB-2",
			"HVAC CO",
			"C2",
			"Beta",
			None,
			"Leak",
			"Scheduled",
			self.start + timedelta(hours=1),
			self.start + timedelta(hours=3),
			"T1",
			"Sarah",
		)
		board = DispatchService(FakeDispatchRepository([self.job, other])).board(
			self.dispatcher, self.start - timedelta(hours=1), self.start + timedelta(hours=4)
		)
		self.assertEqual(board.conflicts[0].job_ids, ("JOB-1", "JOB-2"))

	def test_preview_blocks_conflicting_move(self):
		other = DispatchJob(
			"JOB-2",
			"HVAC CO",
			"C2",
			"Beta",
			None,
			"Leak",
			"Scheduled",
			self.start + timedelta(hours=3),
			self.start + timedelta(hours=5),
			"T1",
			"Sarah",
		)
		store = FakeProposalStore()
		service = DispatchService(FakeDispatchRepository([self.job, other]), store)
		preview = service.preview_change(
			self.dispatcher,
			"JOB-1",
			"T1",
			self.start + timedelta(hours=4),
			self.start + timedelta(hours=6),
			"v1",
		)
		self.assertFalse(preview.can_commit)
		self.assertEqual(preview.conflicts[0].job_ids, ("JOB-2", "JOB-1"))

	def test_preview_then_commit_updates_once(self):
		store = FakeProposalStore()
		repository = FakeDispatchRepository([self.job])
		service = DispatchService(repository, store)
		new_start = self.start + timedelta(hours=3)
		preview = service.preview_change(
			self.dispatcher, "JOB-1", "T1", new_start, new_start + timedelta(hours=2), "v1"
		)
		self.assertTrue(preview.can_commit)
		receipt = service.commit_change(self.dispatcher, preview.proposal.id, "move:1", ActionEngine())
		self.assertEqual(receipt.result["job_id"], "JOB-1")
		self.assertEqual(repository.jobs["JOB-1"].start, new_start)

	def test_technician_sees_only_own_jobs(self):
		other = DispatchJob(
			"JOB-2",
			"HVAC CO",
			"C2",
			"Beta",
			None,
			"Leak",
			"Scheduled",
			self.start,
			self.start + timedelta(hours=1),
			"T2",
			"Mike",
			"other@example.test",
		)
		tech = TenantContext("HVAC CO", "tech@example.test", frozenset({FieldOSRole.TECHNICIAN}))
		board = DispatchService(FakeDispatchRepository([self.job, other])).board(
			tech, self.start - timedelta(hours=1), self.start + timedelta(hours=3)
		)
		self.assertEqual([job.id for job in board.jobs], ["JOB-1"])
