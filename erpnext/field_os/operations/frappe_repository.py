"""ERPNext-backed queries for the operator read model.

Every business query receives and applies the resolved company tenant. The UI
never sends arbitrary filters or doctypes to this boundary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

import frappe

from erpnext.field_os.operations.models import (
	AttentionItem,
	AttentionSeverity,
	RecordLink,
	SearchResult,
)


def _value(row: Any, key: str, default: Any = None) -> Any:
	if isinstance(row, dict):
		return row.get(key, default)
	return getattr(row, key, default)


class FrappeOperationsRepository:
	def list_attention(self, company: str, day: date, limit: int) -> list[AttentionItem]:
		items: list[AttentionItem] = []
		items.extend(self._todays_visits(company, day, limit))
		items.extend(self._unassigned_issues(company, limit))
		items.extend(self._overdue_invoices(company, day, limit))
		items.extend(self._inbox_attention(company, limit))
		return items

	def _todays_visits(self, company: str, day: date, limit: int) -> list[AttentionItem]:
		rows = frappe.get_all(
			"Maintenance Visit",
			filters={"company": company, "mntc_date": day, "docstatus": ["!=", 2]},
			fields=["name", "customer", "status", "mntc_time", "owner"],
			order_by="mntc_time asc, modified desc",
			limit=limit,
		)
		result = []
		for row in rows:
			status = str(_value(row, "status") or "Scheduled")
			visit_time = _value(row, "mntc_time")
			due_at = datetime.combine(
				day, visit_time if isinstance(visit_time, time) else time.min, tzinfo=UTC
			)
			result.append(
				AttentionItem(
					id=f"visit:{_value(row, 'name')}",
					kind="today_jobs",
					severity=AttentionSeverity.WARNING
					if status.lower() == "overdue"
					else AttentionSeverity.INFO,
					title=f"{_value(row, 'customer') or 'Customer'} · {status}",
					summary="Service visit scheduled today",
					record=RecordLink("Maintenance Visit", _value(row, "name"), "Open visit"),
					due_at=due_at,
					owner=_value(row, "owner"),
				)
			)
		return result

	def _unassigned_issues(self, company: str, limit: int) -> list[AttentionItem]:
		rows = frappe.get_all(
			"Issue",
			filters={"company": company, "status": ["not in", ["Closed", "Resolved"]]},
			fields=["name", "subject", "customer", "opening_date", "priority"],
			order_by="priority desc, opening_date asc",
			limit=limit,
		)
		assigned = set()
		if rows:
			assigned = set(
				frappe.get_all(
					"ToDo",
					filters={
						"reference_type": "Issue",
						"reference_name": ["in", [_value(row, "name") for row in rows]],
						"status": "Open",
					},
					pluck="reference_name",
				)
			)
		return [
			AttentionItem(
				id=f"issue:{_value(row, 'name')}",
				kind="unassigned",
				severity=AttentionSeverity.CRITICAL
				if str(_value(row, "priority")).lower() in {"urgent", "high"}
				else AttentionSeverity.WARNING,
				title=_value(row, "subject") or _value(row, "name"),
				summary=f"Unassigned request · {_value(row, 'customer') or 'Unknown customer'}",
				record=RecordLink("Issue", _value(row, "name"), "Triage request"),
			)
			for row in rows
			if _value(row, "name") not in assigned
		]

	def _overdue_invoices(self, company: str, day: date, limit: int) -> list[AttentionItem]:
		rows = frappe.get_all(
			"Sales Invoice",
			filters={
				"company": company,
				"docstatus": 1,
				"outstanding_amount": [">", 0],
				"due_date": ["<", day],
			},
			fields=["name", "customer_name", "due_date", "outstanding_amount", "currency"],
			order_by="due_date asc",
			limit=limit,
		)
		return [
			AttentionItem(
				id=f"invoice:{_value(row, 'name')}",
				kind="overdue",
				severity=AttentionSeverity.CRITICAL,
				title=f"{_value(row, 'customer_name') or 'Customer'} · invoice overdue",
				summary=f"{_value(row, 'currency') or ''} {_value(row, 'outstanding_amount') or 0} outstanding",
				record=RecordLink("Sales Invoice", _value(row, "name"), "Review invoice"),
				metadata={"due_date": str(_value(row, "due_date"))},
			)
			for row in rows
		]

	def _inbox_attention(self, company: str, limit: int) -> list[AttentionItem]:
		now = datetime.now(UTC)
		rows = frappe.get_all(
			"Field OS Communication Thread",
			filters={"company": company, "status": ["in", ["open", "pending"]]},
			fields=[
				"name",
				"subject",
				"channel",
				"classification",
				"assigned_to",
				"sla_due_at",
				"last_message_at",
			],
			order_by="sla_due_at asc, last_message_at desc",
			limit=limit,
		)
		items = []
		for row in rows:
			due_at = _value(row, "sla_due_at")
			if isinstance(due_at, str):
				due_at = datetime.fromisoformat(due_at)
			if due_at and not due_at.tzinfo:
				due_at = due_at.replace(tzinfo=UTC)
			overdue = bool(due_at and due_at <= now)
			unassigned = not _value(row, "assigned_to")
			if not overdue and not unassigned:
				continue
			items.append(
				AttentionItem(
					id=f"inbox:{_value(row, 'name')}",
					kind="inbox",
					severity=AttentionSeverity.CRITICAL if overdue else AttentionSeverity.WARNING,
					title=_value(row, "subject") or f"{_value(row, 'channel')} message",
					summary="SLA overdue" if overdue else "Unassigned Inbox conversation",
					record=RecordLink("Field OS Communication Thread", _value(row, "name"), "Open in Inbox"),
					due_at=due_at,
					owner=_value(row, "assigned_to"),
					metadata={"classification": _value(row, "classification")},
				)
			)
		return items

	def search(self, company: str, query: str, limit: int) -> list[SearchResult]:
		like = f"%{query}%"
		results: list[SearchResult] = []
		results.extend(self._search_customers(company, like, limit))
		for doctype, kind, title_field, subtitle_field in (
			("Maintenance Visit", "job", "name", "customer"),
			("Quotation", "quote", "name", "party_name"),
			("Sales Invoice", "invoice", "name", "customer_name"),
		):
			remaining = limit - len(results)
			if remaining <= 0:
				break
			rows = frappe.get_all(
				doctype,
				filters={"company": company, "name": ["like", like]},
				fields=["name", title_field, subtitle_field],
				order_by="modified desc",
				limit=remaining,
			)
			results.extend(
				SearchResult(
					id=f"{kind}:{_value(row, 'name')}",
					kind=kind,
					title=str(_value(row, title_field) or _value(row, "name")),
					subtitle=str(_value(row, subtitle_field) or doctype),
					record=RecordLink(doctype, _value(row, "name"), "Open"),
				)
				for row in rows
			)
		return results[:limit]

	def _search_customers(self, company: str, like: str, limit: int) -> list[SearchResult]:
		# Customers are global ERP masters, so prove tenant membership through a
		# company-scoped operational document before returning them.
		customer_ids = frappe.get_all(
			"Sales Invoice",
			filters={"company": company, "customer_name": ["like", like], "docstatus": ["!=", 2]},
			pluck="customer",
			distinct=True,
			limit=limit,
		)
		if not customer_ids:
			return []
		rows = frappe.get_all(
			"Customer",
			filters={"name": ["in", customer_ids]},
			fields=["name", "customer_name", "customer_group"],
			limit=limit,
		)
		return [
			SearchResult(
				id=f"customer:{_value(row, 'name')}",
				kind="customer",
				title=_value(row, "customer_name") or _value(row, "name"),
				subtitle=_value(row, "customer_group") or "Customer",
				record=RecordLink("Customer", _value(row, "name"), "Open customer"),
			)
			for row in rows
		]
