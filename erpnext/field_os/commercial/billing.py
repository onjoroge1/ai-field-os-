"""Hosted Stripe subscriptions. Webhooks refresh current state, never trust redirects."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from erpnext.field_os.commercial import native
from erpnext.field_os.commercial.billing_policy import hosted_url, subscription_values
from erpnext.field_os.demo.safety import block_delivery
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context

EVENT = "Field OS Billing Event"
INVOICE = "Field OS Subscription Invoice"
API_VERSION = "2026-08-26.dahlia"


def settings():
	key = os.environ.get("FIELD_OS_STRIPE_KEY", "")
	prices = {
		name: os.environ.get(f"FIELD_OS_STRIPE_PRICE_{name.upper()}", "") for name in ("standard", "pro")
	}
	if not key or not all(p.startswith("price_") for p in prices.values()) or len(set(prices.values())) != 2:
		frappe.throw(
			_(
				"Billing is not configured. Ask your administrator to configure Field OS Stripe prices and credentials."
			)
		)
	live = os.environ.get("FIELD_OS_STRIPE_LIVE", "false").lower() == "true"
	if not key.startswith(("rk_live_", "sk_live_") if live else ("rk_test_", "sk_test_")):
		frappe.throw(_("Billing credential mode does not match this deployment"))
	return key, prices, live


def client():
	from stripe import RequestsClient, StripeClient

	key, prices, live = settings()
	return StripeClient(
		key, stripe_version=API_VERSION, max_network_retries=2, http_client=RequestsClient(timeout=15)
	)


def return_url():
	# Use deployment configuration, never the incoming Host header or a client redirect.
	host = frappe.conf.get("host_name", "").rstrip("/")
	parsed = urlsplit(host)
	if (
		parsed.scheme != "https"
		or not parsed.hostname
		or parsed.username
		or parsed.password
		or parsed.query
		or parsed.fragment
	):
		frappe.throw(_("Set the site's HTTPS host_name before enabling billing"))
	return host + "/desk/field-os"


def owner(company, *, write=True):
	context = resolve_tenant_context(company)
	authorize(context, "admin")
	if write:
		block_delivery(company)
	return context


def digest(company, purpose):
	return hashlib.sha256(json.dumps([frappe.local.site, company, purpose]).encode()).hexdigest()


def checkout(company, plan):
	owner(company)
	key, prices, live = settings()
	if plan not in prices:
		frappe.throw(_("Choose a configured Field OS plan"))
	url = return_url()
	doc = native.subscription(company, lock=True)
	api = client().v1
	if not doc.stripe_customer:
		customer = api.customers.create(
			{"name": company, "metadata": {"field_os": digest(company, "tenant")}},
			options={"idempotency_key": digest(company, "customer")},
		)
		doc.stripe_customer = customer.id
		doc.save(ignore_permissions=True)
	# Recover delayed webhooks before allowing another subscription.
	active = [
		s
		for s in api.subscriptions.list({"customer": doc.stripe_customer, "status": "all", "limit": 100}).data
		if s.status not in {"canceled", "incomplete_expired"}
	]
	if active:
		frappe.throw(
			_("A subscription already exists. Use Manage billing for payment recovery or plan changes.")
		)
	if doc.checkout_session:
		previous = api.checkout.sessions.retrieve(doc.checkout_session)
		if previous.status == "open":
			if doc.checkout_plan != plan:
				frappe.throw(_("Finish or let the current checkout expire before choosing a different plan"))
			return {"url": hosted_url(previous.url, "checkout.stripe.com")}
		if previous.status == "complete":
			frappe.throw(_("Checkout completed. Refresh billing while Stripe confirms the subscription."))
	generation = int(doc.checkout_generation or 0) + 1
	params = {
		"mode": "subscription",
		"customer": doc.stripe_customer,
		"line_items": [{"price": prices[plan], "quantity": 1}],
		"client_reference_id": digest(company, "tenant"),
		"success_url": url,
		"cancel_url": url,
		"subscription_data": {"metadata": {"field_os": digest(company, "tenant")}},
	}
	if doc.status == "trialing" and doc.trial_end:
		end = datetime.combine(getdate(doc.trial_end) + timedelta(days=1), datetime.min.time(), UTC)
		if end > datetime.now(UTC) + timedelta(days=2):
			params["subscription_data"]["trial_end"] = int(end.timestamp())
	# Stable request parameters are necessary for Stripe's idempotency comparison.
	params["integration_identifier"] = "field-os-" + "".join(
		chr(97 + int(c, 16)) for c in digest(company, "checkout")[:8]
	)
	session = api.checkout.sessions.create(
		params, options={"idempotency_key": digest(company, f"checkout:{generation}:{plan}")}
	)
	doc.checkout_session, doc.checkout_plan, doc.checkout_generation = session.id, plan, generation
	doc.save(ignore_permissions=True)
	return {"url": hosted_url(session.url, "checkout.stripe.com")}


def portal(company):
	owner(company)
	doc = native.subscription(company)
	if not doc.stripe_customer:
		frappe.throw(_("Choose a plan before opening billing management"))
	session = client().v1.billing_portal.sessions.create(
		{"customer": doc.stripe_customer, "return_url": return_url()}
	)
	return {"url": hosted_url(session.url, "billing.stripe.com")}


def sync(company):
	doc = native.subscription(company, lock=True)
	if not doc.stripe_customer:
		return
	key, prices, live = settings()
	api = client().v1
	remote = api.subscriptions.list({"customer": doc.stripe_customer, "status": "all", "limit": 100})
	eligible = [s for s in remote.data if s.status not in {"canceled", "incomplete_expired"}]
	if len(eligible) > 1 or remote.has_more:
		frappe.throw(_("Multiple subscriptions need administrator reconciliation"))
	selected = (
		eligible[0] if eligible else next((s for s in remote.data if s.id == doc.stripe_subscription), None)
	)
	if selected:
		if (
			selected.customer != doc.stripe_customer
			or bool(selected.livemode) != live
			or (
				selected.metadata.to_dict() if hasattr(selected.metadata, "to_dict") else selected.metadata
			).get("field_os")
			!= digest(company, "tenant")
		):
			frappe.throw(_("Subscription does not match the Field OS company binding"))
		doc.update(
			subscription_values(
				selected.to_dict() if hasattr(selected, "to_dict") else selected,
				prices,
				native.state(doc),
				datetime.now(UTC),
			)
		)
		doc.billing_synced_at = now_datetime()
		doc.checkout_session = None
		doc.save(ignore_permissions=True)
	for invoice in api.invoices.list({"customer": doc.stripe_customer, "limit": 25}).data:
		if bool(invoice.livemode) != live or invoice.customer != doc.stripe_customer:
			continue
		link = (
			hosted_url(invoice.hosted_invoice_url, "invoice.stripe.com")
			if invoice.hosted_invoice_url
			else None
		)
		values = {
			"company": company,
			"status": invoice.status or "draft",
			"currency": invoice.currency,
			"amount_due": invoice.amount_due,
			"amount_paid": invoice.amount_paid,
			"hosted_url": link,
			"provider_created": invoice.created,
		}
		if frappe.db.exists(INVOICE, invoice.id):
			old = frappe.get_doc(INVOICE, invoice.id)
			if old.company != company:
				frappe.throw(_("Invoice company binding mismatch"))
			old.update(values).save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": INVOICE, "provider_id": invoice.id, **values}).insert(
				ignore_permissions=True
			)


def receive(raw, signature):
	import stripe

	if len(raw) > 256000:
		frappe.throw(_("Billing event is too large"), frappe.ValidationError)
	secret = os.environ.get("FIELD_OS_STRIPE_WEBHOOK_SECRET", "")
	if not secret:
		frappe.throw(_("Billing webhook is not configured"), frappe.PermissionError)
	try:
		event = stripe.Webhook.construct_event(raw, signature, secret, tolerance=300)
	except (ValueError, stripe.SignatureVerificationError):
		frappe.throw(_("Invalid billing event signature"), frappe.PermissionError)
	key, prices, live = settings()
	if bool(event.livemode) != live:
		frappe.throw(_("Billing event environment mismatch"), frappe.PermissionError)
	if event.type not in {
		"checkout.session.completed",
		"customer.subscription.created",
		"customer.subscription.updated",
		"customer.subscription.deleted",
		"invoice.paid",
		"invoice.payment_failed",
		"invoice.payment_action_required",
	}:
		return {"accepted": True, "ignored": True}
	customer = event.data.object.to_dict().get("customer")
	company = (
		frappe.db.get_value(native.SUBSCRIPTION, {"stripe_customer": customer}, "company")
		if customer
		else None
	)
	if not company:
		return {"accepted": True, "ignored": True}
	native.lock_company(company)
	if frappe.db.exists(EVENT, event.id):
		return {"accepted": True, "duplicate": True}
	# Pull current provider state so out-of-order and delayed events cannot restore stale entitlements.
	sync(company)
	frappe.get_doc(
		{
			"doctype": EVENT,
			"provider_id": event.id,
			"company": company,
			"event_type": event.type,
			"provider_created": event.created,
		}
	).insert(ignore_permissions=True)
	return {"accepted": True, "duplicate": False}


def view(company):
	owner(company, write=False)
	doc = native.subscription(company)
	try:
		settings()
		return_url()
		configured = not frappe.db.exists("Field OS Demo Tenant", {"company": company})
	except frappe.ValidationError:
		frappe.clear_messages()
		configured = False
	return {
		"configured": configured,
		"has_customer": bool(doc.stripe_customer),
		"synced_at": doc.billing_synced_at,
		"invoices": frappe.get_all(
			INVOICE,
			filters={"company": company},
			fields=["provider_id", "status", "currency", "amount_due", "amount_paid", "hosted_url"],
			order_by="provider_created desc",
			limit=25,
		),
	}


def reconcile():
	for company in frappe.get_all(
		native.SUBSCRIPTION, filters={"stripe_customer": ["is", "set"]}, pluck="company"
	):
		try:
			sync(company)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="Field OS billing reconciliation failed",
				message="Company subscription refresh failed; inspect provider availability using support diagnostics.",
			)
