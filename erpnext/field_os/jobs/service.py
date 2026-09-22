"""Database outbox; Redis is transport, never the durable source of job state."""

import hashlib
import time
from dataclasses import replace
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

from erpnext.field_os.commercial.native import consume, lock_company, require
from erpnext.field_os.communications.approval import message_digest
from erpnext.field_os.communications.email import EmailSendResult, FrappeEmailProvider, OutboundEmail
from erpnext.field_os.communications.email_frappe import load_email_integration
from erpnext.field_os.communications.frappe_repository import FrappeCommunicationRepository
from erpnext.field_os.communications.models import CommunicationChannel, DeliveryState
from erpnext.field_os.communications.service import CommunicationService
from erpnext.field_os.communications.sms import OutboundSMS, SMSSendResult
from erpnext.field_os.communications.sms_frappe import load_sms_integration
from erpnext.field_os.demo.safety import block_delivery
from erpnext.field_os.jobs.policy import failure_state, retry_seconds
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context
from erpnext.field_os.support.service import audit, reason_text

JOB = "Field OS Job"
KINDS = {"email.send", "sms.send", "email.poll", "sms.poll"}


def locked(name):
	table = frappe.qb.DocType(JOB)
	frappe.qb.from_(table).select(table.name).where(table.name == name).for_update().run()
	return frappe.get_doc(JOB, name)


def admit(company, kind, source, *, actor, digest=""):
	if kind not in KINDS or not source:
		raise ValueError("Unsupported job")
	lock_company(company)
	key = hashlib.sha256(f"{company}\0{kind}\0{source}".encode()).hexdigest()
	name = frappe.db.get_value(JOB, {"job_key": key}, "name")
	if name:
		return frappe.get_doc(JOB, name)
	return frappe.get_doc(
		{
			"doctype": JOB,
			"company": company,
			"job_key": key,
			"kind": kind,
			"source": source,
			"actor": actor,
			"digest": digest,
			"status": "Queued",
			"attempts": 0,
			"next_attempt": now_datetime(),
			"replay_safe": int(kind.endswith(".poll")),
			"correlation_id": getattr(frappe.local, "field_os_correlation", None),
		}
	).insert(ignore_permissions=True)


class DurableSender:
	def __init__(self, context, metric, integration_id):
		self.context, self.metric, self.integration_id = context, metric, integration_id

	def send(self, outbound):
		message = FrappeCommunicationRepository().get_message(self.context.company, outbound.reference_id)
		if not message or message.provider != self.integration_id:
			raise PermissionError("Approved message not found")
		amount = len(set(outbound.to + outbound.cc)) if self.metric == "email" else 1
		consume(self.context.company, self.metric, outbound.reference_id, amount=amount)
		job = admit(
			self.context.company,
			self.metric + ".send",
			message.id,
			actor=self.context.user,
			digest=message_digest(message),
		)
		result = EmailSendResult if self.metric == "email" else SMSSendResult
		return result("job:" + job.name, DeliveryState.QUEUED, now_datetime(), message.metadata)


def prepare_send(job):
	if not frappe.db.get_value("User", job.actor, "enabled"):
		raise PermissionError("Approver is disabled")
	context = resolve_tenant_context(job.company, user=job.actor)
	authorize(context, "communicate")
	metric = job.kind.split(".")[0]
	require(job.company, metric)
	block_delivery(job.company)
	repo = FrappeCommunicationRepository()
	message = repo.get_message(job.company, job.source)
	if not message or message.delivery_state != DeliveryState.QUEUED or message_digest(message) != job.digest:
		raise ValueError("Approved content changed")
	loader = load_email_integration if metric == "email" else load_sms_integration
	integration = loader(integration_id=message.provider)
	sender = integration.from_address if metric == "email" else integration.from_number
	if integration.company != job.company or sender != message.sender.address:
		raise PermissionError("Sender integration changed")
	for recipient in message.recipients:
		if not CommunicationService(repo).can_send(
			job.company,
			recipient.address,
			CommunicationChannel(metric),
			transactional=metric == "email" or bool(message.metadata.get("transactional")),
		):
			raise PermissionError("Recipient consent changed")
	if metric == "email":
		outbound = OutboundEmail(
			sender,
			tuple(x.address for x in message.recipients),
			(),
			message.subject or "",
			message.body,
			job.job_key,
			message.id,
		)
	else:
		outbound = OutboundSMS(sender, message.recipients[0].address, message.body, job.job_key, message.id)
	# Native email only inserts an Email Queue record in this transaction. Other adapters
	# may opt in only when their provider enforces this stable key across timeout/retry.
	job.replay_safe = int(
		type(integration.provider) is FrappeEmailProvider
		or getattr(integration.provider, "supports_idempotency", False) is True
	)
	return repo, message, integration.provider, outbound


def poll(job):
	metric = job.kind.split(".")[0]
	integration_id = job.source.rsplit(":", 1)[0]
	doctype = "Field OS Email Integration" if metric == "email" else "Field OS SMS Integration"
	if not frappe.db.get_value(
		doctype, {"name": integration_id, "company": job.company, "enabled": 1, "poll_enabled": 1}, "name"
	):
		raise ValueError("Mailbox polling disabled")
	loader = load_email_integration if metric == "email" else load_sms_integration
	integration = loader(integration_id=integration_id)
	if metric == "email":
		from erpnext.field_os.api.email import _service
	else:
		from erpnext.field_os.api.sms import _service
	messages, cursor = integration.provider.poll(integration.poll_cursor, 100)
	for message in messages:
		_service(job.company).receive(job.company, integration.id, message)
	frappe.db.set_value(
		doctype, integration.id, {"poll_cursor": cursor, "last_error": None}, update_modified=False
	)


def run(name):
	"""Worker entrypoint. Never whitelist: commits at each durable state boundary.

	Claim and dispatch intent must survive worker death before an external side effect;
	success/failure then commits separately. Framework end-of-job commit is too late.
	"""
	from erpnext.field_os.observability.service import record

	started = time.monotonic()
	if frappe.session.user != "Administrator":
		raise frappe.PermissionError("Jobs run only in the scheduler worker context")
	try:
		job = locked(name)
		if job.status not in {"Queued", "Retry"} or get_datetime(job.next_attempt) > now_datetime():
			frappe.db.rollback()
			return
		frappe.local.field_os_correlation = job.correlation_id or job.name
		job.status, job.attempts = "Running", job.attempts + 1
		job.lease_until = now_datetime() + timedelta(minutes=15)
		job.dispatched = 0
		job.save(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		try:
			job = locked(name)
			if job.kind.endswith(".send"):
				repo, message, provider, outbound = prepare_send(job)
				job.dispatched = 1
				job.save(ignore_permissions=True)
				frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
				job = locked(name)
				result = provider.send(outbound)
				repo.save_message(
					replace(
						message,
						external_id=result.external_id,
						delivery_state=result.state,
						metadata={**message.metadata, **(result.metadata or {})},
						error=None,
					)
				)
			else:
				poll(job)
			record(
				"job",
				company=job.company,
				duration_ms=(time.monotonic() - started) * 1000,
				parent_id=job.name,
			)
			job.status, job.error_code = "Succeeded", None
			job.lease_until = None
			job.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		except Exception as exc:
			frappe.db.rollback()
			job = locked(name)
			job.status = failure_state(
				attempts=job.attempts,
				dispatched=job.dispatched,
				replay_safe=job.replay_safe,
				permanent=isinstance(exc, PermissionError | ValueError | frappe.PermissionError),
			)
			record(
				"job",
				company=job.company,
				duration_ms=(time.monotonic() - started) * 1000,
				failed=True,
				parent_id=job.name,
			)
			job.error_code = "send_failed" if job.kind.endswith(".send") else "poll_failed"
			job.next_attempt = now_datetime() + timedelta(seconds=retry_seconds(job.attempts))
			job.lease_until = None
			job.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	finally:
		pass


def tick():
	"""Bounded DB-to-RQ relay; repeated enqueue is harmless because claims lock the row."""
	now = now_datetime()
	for name in frappe.get_all(
		JOB, filters={"status": "Running", "lease_until": ["<", now]}, pluck="name", limit=100
	):
		job = locked(name)
		if job.status == "Running" and get_datetime(job.lease_until) < now:
			job.status = failure_state(
				attempts=job.attempts, dispatched=job.dispatched, replay_safe=job.replay_safe
			)
			job.error_code, job.next_attempt, job.lease_until = "worker_lost", now, None
			job.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	for name in frappe.get_all(
		JOB,
		filters={"status": ["in", ["Queued", "Retry"]], "next_attempt": ["<=", now]},
		pluck="name",
		order_by="next_attempt asc",
		limit=100,
	):
		frappe.enqueue(
			"erpnext.field_os.jobs.service.run",
			name=name,
			queue="short",
			timeout=600,
			job_id="field-os:" + name,
			deduplicate=True,
			enqueue_after_commit=True,
		)


def schedule_polls():
	slot = str(int(now_datetime().timestamp()) // 900)
	for metric in ("email", "sms"):
		doctype = "Field OS Email Integration" if metric == "email" else "Field OS SMS Integration"
		for row in frappe.get_all(
			doctype, filters={"enabled": 1, "poll_enabled": 1}, fields=["name", "company"]
		):
			# One unfinished poll per integration; do not race mailbox cursors across schedule slots.
			if frappe.db.exists(
				JOB,
				{
					"company": row.company,
					"kind": metric + ".poll",
					"source": ["like", row.name + ":%"],
					"status": ["in", ["Queued", "Retry", "Running"]],
				},
			):
				continue
			admit(row.company, metric + ".poll", row.name + ":" + slot, actor="Administrator")


def listing(company):
	context = resolve_tenant_context(company)
	authorize(context, "admin")
	return frappe.get_all(
		JOB,
		filters={"company": company},
		fields=["name", "kind", "source", "status", "attempts", "next_attempt", "error_code", "modified"],
		order_by="modified desc",
		limit=100,
	)


def replay(company, name, reason, resolution=None, external_id=None):
	context = resolve_tenant_context(company)
	authorize(context, "admin")
	reason = reason_text(reason)
	job = locked(name)
	if job.company != company:
		raise frappe.PermissionError("Job belongs to another company")
	if job.status not in {"Dead", "Uncertain"}:
		raise ValueError("Only failed jobs can be reconciled")
	if job.status == "Uncertain" and resolution not in {"confirmed_not_sent", "confirmed_sent"}:
		raise ValueError("Confirm provider outcome before replay")
	if resolution == "confirmed_sent":
		if not external_id or len(external_id) > 140:
			raise ValueError("Provider receipt is required")
		repo = FrappeCommunicationRepository()
		message = repo.get_message(company, job.source)
		repo.save_message(replace(message, external_id=external_id, delivery_state=DeliveryState.SENT))
		job.status = "Succeeded"
	else:
		job.status, job.attempts, job.dispatched = "Queued", 0, 0
		job.next_attempt = now_datetime()
	job.save(ignore_permissions=True)
	audit(
		company,
		"job.reconciled",
		reference=name,
		details={"reason": reason, "resolution": resolution or "retry"},
	)
	return listing(company)
