"""Communication events projected into Customer 360."""

from __future__ import annotations

import frappe

from erpnext.field_os.customers.service import TimelineEvent


class FrappeCustomerCommunicationTimeline:
	def list_events(self, company: str, customer_id: str, limit: int) -> list[TimelineEvent]:
		thread_ids = frappe.get_all(
			"Field OS Communication Thread",
			filters={"company": company, "customer": customer_id},
			pluck="name",
			limit=max(1, min(limit, 500)),
		)
		if not thread_ids:
			return []
		rows = frappe.get_all(
			"Field OS Communication Message",
			filters={"company": company, "thread": ["in", thread_ids]},
			fields=["name", "channel", "direction", "subject", "body", "delivery_status", "occurred_at"],
			order_by="occurred_at desc",
			limit=max(1, min(limit, 500)),
		)
		return [
			TimelineEvent(
				f"message:{row.name}",
				row.channel,
				f"{row.channel.upper()} · {row.direction}",
				row.subject or (row.body[:100] if row.body else row.delivery_status),
				row.occurred_at,
				"Field OS Communication Message",
				row.name,
			)
			for row in rows
		]
