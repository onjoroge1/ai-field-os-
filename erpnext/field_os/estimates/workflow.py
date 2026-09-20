"""Transactional estimate delivery and customer decisions.

The quotation, approval receipt and native Email Queue entry commit together.
Sending does not happen inside an HTTP transaction; Frappe's mail worker owns delivery.
"""

import hashlib
import json
import secrets
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from html import escape

import frappe
from frappe import _
from frappe.utils import get_datetime, get_url, now_datetime, strip_html

from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.actions.validation import require_proposal
from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.communications.frappe_repository import FrappeCommunicationRepository
from erpnext.field_os.communications.models import CommunicationChannel
from erpnext.field_os.communications.service import CommunicationService
from erpnext.field_os.estimates.frappe_repository import (
	DECISION,
	ESTIMATE,
	FrappeEstimateRepository,
	document,
	integration,
	recipients,
	version,
)
from erpnext.field_os.estimates.service import EstimateService
from erpnext.field_os.security.authorization import authorize


def detail(company, name):
	doc, quote = document(company, name)
	result = {
		key: doc.get(key)
		for key in (
			"name",
			"customer",
			"quotation",
			"status",
			"recipient",
			"email_integration",
			"sent_at",
			"approved_by",
			"revision_of",
		)
	}
	result.update(
		version=version(doc, quote),
		currency=quote.currency,
		valid_until=quote.valid_till,
		net_total=quote.net_total,
		taxes=quote.total_taxes_and_charges,
		total=quote.grand_total,
		tax_template=quote.taxes_and_charges,
		items=[
			{
				"item_code": row.item_code,
				"description": strip_html(row.description or row.item_name or row.item_code),
				"qty": row.qty,
				"rate": row.rate,
				"amount": row.amount,
				"warehouse": row.warehouse,
				"on_hand": FrappeEstimateRepository.stock(company, row.item_code, row.warehouse),
			}
			for row in quote.items
		],
		delivery_status=frappe.db.get_value("Email Queue", doc.email_queue, "status")
		if doc.email_queue
		else None,
		decisions=frappe.get_all(
			DECISION,
			filters={"company": company, "field_os_estimate": name},
			fields=["decision", "customer_name", "decided_at", "comment", "evidence", "recorded_by"],
		),
	)
	return result


def preview(context, name):
	authorize(context, "quote")
	doc, quote = document(context.company, name)
	if not doc.recipient or doc.recipient not in recipients(doc.customer):
		frappe.throw(_("Choose an email address linked to this customer"))
	integration(context.company, doc.email_integration)
	if quote.docstatus or (
		quote.valid_till and get_datetime(quote.valid_till).date() < now_datetime().date()
	):
		frappe.throw(_("Only a current draft quotation can be sent"))
	proposal, shortages = EstimateService(
		FrappeEstimateRepository(), FrappeCacheProposalStore()
	).preview_send(context, name)
	return {
		"proposal": asdict(proposal),
		"estimate": detail(context.company, name),
		"shortages": [asdict(row) for row in shortages],
	}


def approve(context, proposal_id, key):
	authorize(context, "quote")
	if not key or len(key) > 140:
		frappe.throw(_("A send key of at most 140 characters is required"))
	key_hash = hashlib.sha256(f"{context.company}\0{context.user}\0send_estimate\0{key}".encode()).hexdigest()
	previous = frappe.db.get_value(
		ESTIMATE, {"send_key_hash": key_hash}, ["name", "proposal_id"], as_dict=True
	)
	if previous:
		if previous.proposal_id != proposal_id:
			frappe.throw(_("Send key was already used for a different approval"))
		return detail(context.company, previous.name)
	store = FrappeCacheProposalStore()
	proposal = require_proposal(
		store.load(context.company, proposal_id), context, tool="send_estimate", risk=RiskClass.EXTERNAL
	)
	doc, quote = document(context.company, proposal.arguments["estimate_id"], lock=True)
	if doc.proposal_id == proposal_id and doc.idempotency_key == key and doc.approved_by == context.user:
		return detail(context.company, doc.name)
	if (
		doc.status != "Draft"
		or quote.docstatus
		or version(doc, quote) != proposal.arguments.get("expected_version")
	):
		frappe.throw(_("Estimate changed. Regenerate its preview."))
	if proposal.expires_at <= datetime.now(UTC):
		frappe.throw(_("Estimate preview expired. Regenerate it."))
	if doc.recipient not in recipients(doc.customer):
		frappe.throw(_("Customer contact changed. Update the recipient."))
	if not CommunicationService(FrappeCommunicationRepository()).can_send(
		context.company, doc.recipient, CommunicationChannel.EMAIL, transactional=True
	):
		frappe.throw(_("Customer has opted out of email"))
	mailbox = integration(context.company, doc.email_integration)
	if quote.valid_till and get_datetime(quote.valid_till).date() < now_datetime().date():
		frappe.throw(_("Quotation has expired"))
	# Quote capability was checked above and the exact tenant/customer were verified.
	approved_amounts = (
		quote.currency,
		quote.grand_total,
		quote.total_taxes_and_charges,
		[(row.item_code, row.qty, row.rate, row.amount) for row in quote.items],
	)
	quote.flags.ignore_permissions = True
	quote.submit()
	if approved_amounts != (
		quote.currency,
		quote.grand_total,
		quote.total_taxes_and_charges,
		[(row.item_code, row.qty, row.rate, row.amount) for row in quote.items],
	):
		frappe.throw(_("Pricing changed while submitting. Save an updated draft and review it again."))
	token = secrets.token_urlsafe(32)
	expires = now_datetime() + timedelta(days=14)
	if quote.valid_till:
		expires = min(expires, get_datetime(quote.valid_till) + timedelta(days=1))
	doc.update(
		{
			"status": "Sent",
			"quote_modified": quote.modified,
			"proposal_id": proposal_id,
			"idempotency_key": key,
			"approved_by": context.user,
			"sent_at": now_datetime(),
			"send_key_hash": key_hash,
			"approval_token_hash": hashlib.sha256(token.encode()).hexdigest(),
			"token_expires_at": expires,
		}
	)
	url = get_url(f"/fieldos-estimate?token={token}")
	rows = "".join(
		f"<tr><td>{escape(strip_html(row.description or row.item_name or row.item_code))}</td><td>{row.qty:g}</td><td>{row.amount:,.2f}</td></tr>"
		for row in quote.items
	)
	body = (
		f"<h1>Estimate {escape(quote.name)}</h1><p>{escape(doc.company)}</p>"
		f"<table><thead><tr><th>Work or part</th><th>Quantity</th><th>Amount</th></tr></thead><tbody>{rows}</tbody></table>"
		f"<p>Total including taxes: {escape(quote.currency)} {quote.grand_total:,.2f}</p>"
		f'<p><a href="{escape(url, quote=True)}">Review and approve or decline your estimate</a></p>'
		f"<p>Sign in with {escape(doc.recipient)} to record your decision. "
		"If you do not have an account, reply to this email so we can help.</p>"
		f"<p>This private approval link expires {expires.date().isoformat()}. Reply with any questions.</p>"
	)
	thread = frappe.get_doc(
		{
			"doctype": "Field OS Communication Thread",
			"company": context.company,
			"channel": "email",
			"subject": f"Estimate {quote.name}",
			"status": "pending",
			"customer": doc.customer,
			"quote": quote.name,
			"last_message_at": now_datetime(),
			"participants": [{"address": doc.recipient, "participant_role": "customer"}],
		}
	).insert(ignore_permissions=True)
	message = frappe.get_doc(
		{
			"doctype": "Field OS Communication Message",
			"company": context.company,
			"thread": thread.name,
			"channel": "email",
			"direction": "outbound",
			"sender_address": mailbox.from_address,
			"sender_role": "user",
			"subject": thread.subject,
			"body": f"Estimate {quote.name}: {quote.currency} {quote.grand_total:,.2f}. Sent to {doc.recipient} for a customer decision.",
			"occurred_at": now_datetime(),
			"delivery_status": "queued",
			"provider": doc.email_integration,
			"recipients_json": json.dumps([{"address": doc.recipient, "participant_role": "customer"}]),
		}
	).insert(ignore_permissions=True)
	from erpnext.field_os.demo.safety import block_delivery

	block_delivery(context.company)
	queued = frappe.sendmail(
		recipients=[doc.recipient],
		sender=mailbox.from_address,
		subject=thread.subject,
		message=body,
		reference_doctype=ESTIMATE,
		reference_name=doc.name,
		delayed=True,
		now=False,
	)
	if not queued:
		frappe.throw(_("Email could not be queued. Check the outgoing email account and suppression list."))
	doc.email_queue, doc.communication_message = queued.name, message.name
	doc.save(ignore_permissions=True)
	return detail(context.company, doc.name)


def token_document(token, *, lock=False):
	if not isinstance(token, str) or len(token) < 40 or len(token) > 100:
		frappe.throw(_("Approval link is invalid or expired"), frappe.PermissionError)
	digest = hashlib.sha256(token.encode()).hexdigest()
	row = frappe.db.get_value(ESTIMATE, {"approval_token_hash": digest}, ["name", "company"], as_dict=True)
	if not row:
		frappe.throw(_("Approval link is invalid or expired"), frappe.PermissionError)
	doc, quote = document(row.company, row.name, lock=lock)
	if not doc.token_expires_at or get_datetime(doc.token_expires_at) <= now_datetime():
		frappe.throw(_("Approval link is invalid or expired"), frappe.PermissionError)
	if quote.docstatus != 1 or get_datetime(quote.modified) != get_datetime(doc.quote_modified):
		frappe.throw(_("This quotation has changed. Please request a new estimate."))
	return doc, quote


def customer_document(token, *, lock=False):
	"""Require both the private link and the authenticated, enabled recipient."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Sign in with the estimate recipient's account"), frappe.PermissionError)
	account = frappe.db.get_value("User", user, ["email", "enabled"], as_dict=True)
	if not account or not account.enabled:
		frappe.throw(_("Sign in with the estimate recipient's account"), frappe.PermissionError)
	doc, quote = token_document(token, lock=lock)
	if not account.email or account.email.casefold() != doc.recipient.casefold():
		frappe.throw(_("This estimate belongs to a different customer account"), frappe.PermissionError)
	return doc, quote


def decide(doc, quote, decision, customer_name, comment, evidence, recorded_by):
	if decision not in {"Approved", "Rejected"} or not customer_name.strip() or not evidence.strip():
		frappe.throw(_("A decision, customer approver and approval evidence are required"))
	if len(customer_name) > 140 or len(comment) > 2000 or len(evidence) > 2000:
		frappe.throw(_("Approval details are too long"))
	if doc.status == decision:
		return {"status": decision, "estimate": doc.name}
	if (
		decision == "Approved"
		and quote.valid_till
		and get_datetime(quote.valid_till).date() < now_datetime().date()
	):
		frappe.throw(_("Expired estimates require a new revision before approval"))
	if (
		doc.status != "Sent"
		or quote.docstatus != 1
		or get_datetime(quote.modified) != get_datetime(doc.quote_modified)
	):
		frappe.throw(_("Estimate is no longer awaiting this decision"))
	frappe.get_doc(
		{
			"doctype": DECISION,
			"company": doc.company,
			"estimate": doc.quotation,
			"field_os_estimate": doc.name,
			"decision": decision,
			"customer_name": customer_name.strip(),
			"comment": comment.strip(),
			"decided_at": now_datetime(),
			"evidence": evidence.strip(),
			"recorded_by": recorded_by,
		}
	).insert(ignore_permissions=True)
	doc.status = decision
	doc.save(ignore_permissions=True)
	return {"status": decision, "estimate": doc.name}


def sync_delivery():
	"""Mirror native queue outcomes into Inbox; the mail worker handles retries."""
	for row in frappe.get_all(
		ESTIMATE,
		filters={"email_queue": ["is", "set"]},
		fields=["email_queue", "communication_message"],
		limit_page_length=0,
	):
		state = frappe.db.get_value("Email Queue", row.email_queue, "status")
		if row.communication_message and state in {"Sent", "Error", "Not Sent", "Sending", "Partially Sent"}:
			frappe.db.set_value(
				"Field OS Communication Message",
				row.communication_message,
				"delivery_status",
				"sent" if state == "Sent" else "failed" if state == "Error" else "queued",
				update_modified=False,
			)
