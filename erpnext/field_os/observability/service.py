"""Redacted JSON spans and rolling Redis aggregates independent of SQL rollbacks."""

import hashlib
import json
import os
import time
from datetime import timedelta
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from erpnext.field_os.observability.policy import GROUPS, cost_microusd, latency_bucket, operation, percentile
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context

ALERT = "Field OS Operational Alert"
RETENTION_SECONDS = 7200


def key(company, minute):
	return (
		"fieldos-metrics:" + hashlib.sha256(f"{frappe.local.site}\0{company}\0{minute}".encode()).hexdigest()
	)


def record(kind, *, company=None, duration_ms=0, failed=False, cost=None, parent_id=None):
	# No arbitrary tags, URL, request payload, prompt, contact details, exception text or secrets.
	kind = kind if kind in GROUPS | {"ai", "job", "other"} else "other"
	company = company or getattr(frappe.local, "field_os_company", None)
	try:
		duration_ms = max(0, min(int(duration_ms), 3_600_000))
		trace = getattr(frappe.local, "field_os_correlation", None) or uuid4().hex
		span = {
			"event": kind,
			"trace_id": trace,
			"span_id": uuid4().hex,
			"parent_id": parent_id,
			"tenant": company,
			"duration_ms": duration_ms,
			"outcome": "error" if failed else "ok",
		}
		if cost is not None:
			span["estimated_cost_microusd"] = cost
		frappe.logger("field_os", allow_site=True).info(json.dumps(span, separators=(",", ":")))
		if not company:
			return
		redis_key = key(company, int(time.time() // 60))
		pipe = frappe.cache.pipeline(transaction=True)
		for field, amount in {
			"count": 1,
			"errors": int(bool(failed)),
			"duration_ms": duration_ms,
			"latency:" + latency_bucket(duration_ms): 1,
			"feature:" + kind: 1,
			"cost_microusd": cost or 0,
			"unpriced_ai": int(kind == "ai" and cost is None),
		}.items():
			pipe.hincrby(redis_key, field, amount)
		pipe.expire(redis_key, RETENTION_SECONDS).execute()
	except Exception:
		# Telemetry cannot roll back a successful business operation. The external log/Redis
		# heartbeat monitor must detect missing telemetry; the dashboard reports cache failure.
		return


def model_cost(reply):
	try:
		rates = json.loads(os.environ.get("FIELD_OS_MODEL_PRICES_USD_JSON", "{}"))
		return cost_microusd(reply.input_tokens, reply.output_tokens, rates.get(reply.model))
	except (ValueError, TypeError, AttributeError):
		return None


def request_finished(response):
	started = getattr(frappe.local, "field_os_started", None)
	if started is not None:
		record(
			operation(getattr(frappe.local, "field_os_endpoint", "")),
			duration_ms=(time.monotonic() - started) * 1000,
			failed=response.status_code >= 400,
		)


def aggregate(company):
	pipe = frappe.cache.pipeline(transaction=False)
	minute = int(time.time() // 60)
	for offset in range(60):
		pipe.hgetall(key(company, minute - offset))
	totals = {}
	for row in pipe.execute():
		for field, amount in row.items():
			field = field.decode() if isinstance(field, bytes) else field
			totals[field] = totals.get(field, 0) + int(amount)
	count = totals.get("count", 0)
	return {
		"spans": count,
		"errors": totals.get("errors", 0),
		"error_rate": round(totals.get("errors", 0) / count, 4) if count else 0,
		"p95_ms": percentile(
			{k.removeprefix("latency:"): v for k, v in totals.items() if k.startswith("latency:")}
		),
		"estimated_ai_cost_usd": totals.get("cost_microusd", 0) / 1_000_000,
		"unpriced_ai": totals.get("unpriced_ai", 0),
		"features": {k.removeprefix("feature:"): v for k, v in totals.items() if k.startswith("feature:")},
	}


def health(company):
	metrics = aggregate(company)
	from erpnext.field_os.jobs.service import JOB

	metrics["dead_jobs"] = frappe.db.count(JOB, {"company": company, "status": "Dead"})
	metrics["uncertain_jobs"] = frappe.db.count(JOB, {"company": company, "status": "Uncertain"})
	metrics["overdue_jobs"] = frappe.db.count(
		JOB,
		{
			"company": company,
			"status": ["in", ["Queued", "Retry"]],
			"next_attempt": ["<", now_datetime() - timedelta(minutes=5)],
		},
	)
	return metrics


def conditions(metrics):
	return {
		"error_rate": metrics["spans"] >= 20 and metrics["error_rate"] >= 0.05,
		"slow_operations": metrics["spans"] >= 20
		and (metrics["p95_ms"] == "overflow" or (metrics["p95_ms"] or 0) > 2000),
		"worker_backlog": metrics["overdue_jobs"] > 0,
		"dead_jobs": metrics["dead_jobs"] > 0,
		"uncertain_delivery": metrics["uncertain_jobs"] > 0,
	}


def evaluate():
	for company in frappe.get_all("Company", pluck="name"):
		for code, active in conditions(health(company)).items():
			name = hashlib.sha256(f"{company}\0{code}".encode()).hexdigest()
			if frappe.db.exists(ALERT, name):
				frappe.db.set_value(
					ALERT, name, {"status": "Open" if active else "Resolved", "last_checked": now_datetime()}
				)
			elif active:
				frappe.get_doc(
					{
						"doctype": ALERT,
						"alert_key": name,
						"company": company,
						"code": code,
						"status": "Open",
						"last_checked": now_datetime(),
					}
				).insert(ignore_permissions=True)


def dashboard(company):
	context = resolve_tenant_context(company)
	authorize(context, "admin")
	metrics = health(company)
	return {
		"window_minutes": 60,
		"metrics": metrics,
		"conditions": [code for code, active in conditions(metrics).items() if active],
		"alerts": frappe.get_all(
			ALERT,
			filters={"company": company, "status": "Open"},
			fields=["code", "creation", "last_checked"],
			limit=20,
		),
	}
