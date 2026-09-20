"""Explicitly approved invoice emails and follow-ups with durable native queue receipts."""

import json
from dataclasses import asdict
from html import escape

import frappe
from frappe import _
from frappe.utils import now_datetime, strip_html

from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.communications.frappe_repository import FrappeCommunicationRepository
from erpnext.field_os.communications.models import CommunicationChannel
from erpnext.field_os.communications.service import CommunicationService
from erpnext.field_os.completions import billing
from erpnext.field_os.completions import repository as repo
from erpnext.field_os.estimates.frappe_repository import integration, recipients
from erpnext.field_os.security.authorization import authorize


def validate(context, doc, invoice, recipient, integration_id, kind):
	authorize(context, "invoice")
	authorize(context, "communicate")
	if doc.status != "Invoiced" or invoice.docstatus != 1:
		frappe.throw(_("Post the invoice with financial approval before sending it"))
	if kind not in {"Invoice", "Follow-up"}:
		frappe.throw(_("Choose an invoice email or follow-up"))
	if kind == "Follow-up" and invoice.outstanding_amount <= 0:
		frappe.throw(_("A paid invoice does not need a payment follow-up"))
	if recipient not in recipients(doc.customer):
		frappe.throw(_("Choose an email address linked to this customer"))
	if not CommunicationService(FrappeCommunicationRepository()).can_send(
		context.company, recipient, CommunicationChannel.EMAIL, transactional=True
	):
		frappe.throw(_("Customer has opted out of email"))
	return integration(context.company, integration_id)


def preview(context, name, recipient, integration_id, kind):
	doc, _job = repo.document(context, name)
	invoice = billing.invoice_document(doc)
	validate(context, doc, invoice, recipient, integration_id, kind)
	args = {
		"completion_id": name,
		"invoice": invoice.name,
		"invoice_modified": str(invoice.modified),
		"recipient": recipient,
		"integration": integration_id,
		"kind": kind,
		"outstanding": invoice.outstanding_amount,
		"total": invoice.grand_total,
		"currency": invoice.currency,
		"due_date": str(invoice.due_date),
	}
	item = billing.proposal(context, "send_completion_invoice", args, RiskClass.EXTERNAL)
	return {"proposal": asdict(item), **args}


def approve(context, proposal_id, key):
	authorize(context, "invoice")
	authorize(context, "communicate")
	digest = billing.retry_key(context, "send_completion_invoice", key)
	previous = frappe.db.get_value(
		repo.NOTICE,
		{"company": context.company, "key_hash": digest},
		["name", "completion", "proposal_id"],
		as_dict=True,
	)
	if previous:
		if previous.proposal_id != proposal_id:
			frappe.throw(_("Retry key belongs to another email approval"))
		return repo.detail(context, previous.completion)
	item = billing.load_proposal(context, proposal_id, "send_completion_invoice", RiskClass.EXTERNAL)
	args = item.arguments
	doc, _job = repo.document(context, args["completion_id"], lock=True)
	if frappe.db.exists(repo.NOTICE, {"key_hash": digest, "proposal_id": proposal_id}):
		return repo.detail(context, doc.name)
	invoice = billing.invoice_document(doc, lock=True)
	mailbox = validate(context, doc, invoice, args["recipient"], args["integration"], args["kind"])
	if (invoice.name, str(invoice.modified), invoice.outstanding_amount, invoice.grand_total) != (
		args["invoice"],
		args["invoice_modified"],
		args["outstanding"],
		args["total"],
	):
		frappe.throw(_("Invoice or payment status changed. Review a new email preview."))
	subject = f"{args['kind']} {invoice.name} — {doc.company}"
	rows = "".join(
		f"<tr><td>{escape(strip_html(r.description or r.item_code))}</td><td>{r.qty:g}</td><td>{r.amount:,.2f}</td></tr>"
		for r in invoice.items
	)
	body = f"<h1>{escape(args['kind'])} {escape(invoice.name)}</h1><p>{escape(doc.company)} · {escape(invoice.customer_name)}</p><p>Service visit {escape(doc.visit)}</p><table><thead><tr><th>Work or part</th><th>Quantity</th><th>Amount</th></tr></thead><tbody>{rows}</tbody></table><p>Tax: {escape(invoice.currency)} {invoice.total_taxes_and_charges:,.2f}</p><p>Total: {escape(invoice.currency)} {invoice.grand_total:,.2f}</p><p>Outstanding: {escape(invoice.currency)} {invoice.outstanding_amount:,.2f}</p><p>Due: {invoice.due_date}</p><p>Reply to this email with questions or to arrange payment.</p>"
	thread = frappe.get_doc(
		{
			"doctype": "Field OS Communication Thread",
			"company": context.company,
			"channel": "email",
			"subject": subject,
			"status": "pending",
			"customer": doc.customer,
			"invoice": invoice.name,
			"last_message_at": now_datetime(),
			"participants": [{"address": args["recipient"], "participant_role": "customer"}],
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
			"subject": subject,
			"body": body,
			"occurred_at": now_datetime(),
			"delivery_status": "queued",
			"provider": args["integration"],
			"recipients_json": json.dumps([{"address": args["recipient"], "participant_role": "customer"}]),
		}
	).insert(ignore_permissions=True)
	queued = frappe.sendmail(
		recipients=[args["recipient"]],
		sender=mailbox.from_address,
		subject=subject,
		message=body,
		reference_doctype=repo.COMPLETION,
		reference_name=doc.name,
		delayed=True,
		now=False,
	)
	if not queued:
		frappe.throw(_("Invoice email could not be queued. Check the outgoing account and suppression list."))
	frappe.get_doc(
		{
			"doctype": repo.NOTICE,
			"company": context.company,
			"completion": doc.name,
			"invoice": invoice.name,
			"recipient": args["recipient"],
			"kind": args["kind"],
			"email_queue": queued.name,
			"message": message.name,
			"approved_by": context.user,
			"proposal_id": proposal_id,
			"key_hash": digest,
		}
	).insert(ignore_permissions=True)
	return repo.detail(context, doc.name)


def sync_delivery():
	for row in frappe.get_all(repo.NOTICE, fields=["email_queue", "message"], limit_page_length=0):
		state = frappe.db.get_value("Email Queue", row.email_queue, "status")
		if state in {"Sent", "Error", "Not Sent", "Sending", "Partially Sent"}:
			frappe.db.set_value(
				"Field OS Communication Message",
				row.message,
				"delivery_status",
				"sent" if state == "Sent" else "failed" if state == "Error" else "queued",
				update_modified=False,
			)
