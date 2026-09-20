"""Map the initial dispatch workspace onto ERPNext Maintenance Visits."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

import frappe

from erpnext.field_os.dispatch.models import DispatchJob, TechnicianStatus
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context


def _value(row: Any, key: str, default=None):
	return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _as_time(value: Any) -> time:
	if isinstance(value, time):
		return value
	if isinstance(value, timedelta):
		seconds = int(value.total_seconds()) % (24 * 60 * 60)
		return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
	if isinstance(value, str) and value:
		return time.fromisoformat(value)
	return time.min


class FrappeDispatchRepository:
	def ensure_available(self, company, technician_id, start, end, exclude=None, items=()):
		from erpnext.field_os.onboarding.native import check_schedule

		check_schedule(company, technician_id, start, end, items)
		# All Field OS scheduling paths serialize on the same technician record.
		frappe.db.get_value("Sales Person", technician_id, "name", for_update=True)
		start, end = start.replace(tzinfo=UTC), end.replace(tzinfo=UTC)
		for job in self.list_jobs(company, start - timedelta(days=1), end + timedelta(days=1)):
			if (
				job.id != exclude
				and job.technician_id == technician_id
				and job.status != "Fully Completed"
				and start < job.end
				and end > job.start
			):
				raise ValueError("Technician already has a service job in this time window")

	def list_jobs(self, company: str, start: datetime, end: datetime) -> list[DispatchJob]:
		rows = frappe.get_all(
			"Maintenance Visit",
			filters={
				"company": company,
				"mntc_date": ["between", [start.date(), end.date()]],
				"docstatus": ["!=", 2],
			},
			fields=[
				"name",
				"customer",
				"customer_name",
				"customer_address",
				"maintenance_type",
				"completion_status",
				"status",
				"docstatus",
				"mntc_date",
				"mntc_time",
				"modified",
			],
			order_by="mntc_date asc, mntc_time asc",
			limit=500,
		)
		assignments = self._assignments([_value(row, "name") for row in rows])
		technicians = {item.id: item for item in self.list_technicians(company)}
		return [self._job(company, row, assignments, technicians) for row in rows]

	def list_technicians(self, company: str) -> list[TechnicianStatus]:
		rows = frappe.get_all(
			"Sales Person",
			filters={"enabled": 1, "is_group": 0},
			fields=["name", "sales_person_name", "employee"],
			order_by="sales_person_name asc",
			limit=500,
		)
		employee_ids = [_value(row, "employee") for row in rows if _value(row, "employee")]
		users = {}
		if employee_ids:
			users = {
				_value(row, "name"): _value(row, "user_id")
				for row in frappe.get_all(
					"Employee",
					filters={"company": company, "name": ["in", employee_ids], "status": "Active"},
					fields=["name", "user_id"],
				)
			}
		return [
			TechnicianStatus(
				_value(row, "name"),
				_value(row, "sales_person_name") or _value(row, "name"),
				"available",
				users.get(_value(row, "employee")),
			)
			for row in rows
			if _value(row, "employee") in users
		]

	def get_job(self, company: str, job_id: str) -> DispatchJob:
		rows = frappe.get_all(
			"Maintenance Visit",
			filters={"company": company, "name": job_id, "docstatus": ["!=", 2]},
			fields=[
				"name",
				"customer",
				"customer_name",
				"customer_address",
				"maintenance_type",
				"completion_status",
				"status",
				"docstatus",
				"mntc_date",
				"mntc_time",
				"modified",
			],
			limit=1,
		)
		if not rows:
			raise ValueError("Job not found in tenant")
		assignments = self._assignments([job_id])
		technicians = {item.id: item for item in self.list_technicians(company)}
		return self._job(company, rows[0], assignments, technicians)

	def update_assignment(self, company, job_id, technician_id, start, end, expected_version):
		authorize(resolve_tenant_context(company), "dispatch")
		frappe.db.get_value("Maintenance Visit", job_id, "name", for_update=True)
		doc = frappe.get_doc("Maintenance Visit", job_id)
		if doc.company != company:
			raise PermissionError("Cross-tenant dispatch change rejected")
		if doc.docstatus != 0:
			raise ValueError("Only planned visits can be reassigned")
		if expected_version and str(doc.modified) != str(expected_version):
			raise ValueError("Job changed since preview; refresh before retrying")
		employee = frappe.db.get_value(
			"Sales Person",
			{"name": technician_id, "enabled": 1, "is_group": 0},
			"employee",
		)
		if not employee or not frappe.db.exists(
			"Employee", {"name": employee, "company": company, "status": "Active"}
		):
			raise ValueError("Technician is not active")
		if not doc.purposes:
			raise ValueError("Maintenance Visit has no service lines to assign")
		self.ensure_available(
			company, technician_id, start, end, exclude=job_id, items=[row.item_code for row in doc.purposes]
		)
		doc.mntc_date = start.date()
		doc.mntc_time = start.time().replace(tzinfo=None)
		for purpose in doc.purposes:
			purpose.service_person = technician_id
		# Dispatch capability, company, version and active technician were verified above.
		doc.save(ignore_permissions=True)
		return self.get_job(company, job_id)

	def _assignments(self, job_ids: list[str]) -> dict[str, str]:
		if not job_ids:
			return {}
		rows = frappe.get_all(
			"Maintenance Visit Purpose",
			filters={"parent": ["in", job_ids], "parenttype": "Maintenance Visit"},
			fields=["parent", "service_person", "idx"],
			order_by="parent asc, idx asc",
		)
		result = {}
		for row in rows:
			if _value(row, "service_person") and _value(row, "parent") not in result:
				result[_value(row, "parent")] = _value(row, "service_person")
		return result

	@staticmethod
	def _job(company, row, assignments, technicians):
		job_id = _value(row, "name")
		start = datetime.combine(_value(row, "mntc_date"), _as_time(_value(row, "mntc_time")), tzinfo=UTC)
		technician_id = assignments.get(job_id)
		technician = technicians.get(technician_id)
		status = (
			"Scheduled"
			if _value(row, "docstatus") == 0
			else _value(row, "completion_status") or _value(row, "status") or "Scheduled"
		)
		return DispatchJob(
			job_id,
			company,
			_value(row, "customer"),
			_value(row, "customer_name") or _value(row, "customer"),
			_value(row, "customer_address"),
			_value(row, "maintenance_type") or "Service visit",
			status,
			start,
			start + timedelta(hours=2),
			technician_id,
			technician.name if technician else None,
			technician.user if technician else None,
			str(_value(row, "modified") or ""),
		)
