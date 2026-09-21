# Roadmap PR24 — subscription billing

The owner uses Plan & usage to review a plan in hosted Stripe Checkout, open the
Customer Portal, inspect the latest 25 invoices and refresh payment state. All
prices come from server-configured Stripe Price IDs. Checkout displays the price
before the owner confirms. No charge or account resource is created by installing
this code.

Provision a separate Field OS Stripe sandbox. Configure `FIELD_OS_STRIPE_KEY`
with a restricted key, `FIELD_OS_STRIPE_PRICE_STANDARD`,
`FIELD_OS_STRIPE_PRICE_PRO`, `FIELD_OS_STRIPE_WEBHOOK_SECRET`, and
`FIELD_OS_STRIPE_LIVE=false`. Set the Frappe site's `host_name` to its canonical
HTTPS origin. Store keys in the deployment secret manager and inject them into
the server environment. Never reuse another product's sandbox or production keys.
Use separate Stripe Products for Standard and Pro. The Portal configuration must
limit changes to these two plan prices with quantity one.

Register the POST endpoint `/api/method/erpnext.field_os.api.billing.webhook` for
the event allowlist in `commercial/billing.py`. It verifies the raw-body Stripe
signature with a five-minute tolerance, checks test/live mode, resolves the
company using its saved customer binding, and stores a unique permanent event
receipt after refreshing current provider state. Out-of-order event payloads
cannot overwrite newer provider state. An hourly reconciliation repairs missed
events. The webhook must receive the repository's required security review
before the PR can land; do not suppress that rule.

Trials keep their original end date when checking out. Delinquency gets one
seven-day grace window; repeated failures cannot extend it. Expiry, cancellation,
unpaid and paused states become read-only. Billing recovery remains available.
Existing data and users are retained on downgrades; limits block new admission.
Local metering enforces included allowances, not automatic usage-based charges.

Before enabling live billing, validate checkout, customer portal, renewal,
failed-payment recovery and cancellation in the Field OS sandbox. Repository
acceptance tests verify the SDK boundary and signed events with deterministic
provider fixtures; they do not claim a live Stripe transaction. Configure taxes
and registrations before charging customers. Automatic Stripe Tax is not enabled
by this PR; an active registration and tax setup need verification first.

References: https://docs.stripe.com/billing/subscriptions/build-subscriptions
and https://docs.stripe.com/webhooks . Native permission model:
https://docs.frappe.io/framework/user/en/basics/users-and-permissions
