# Roadmap PR23 — plans and usage

Companies receive one persistent 30-day trial when provisioned or migrated. The
trial is not renewed by logging in. `Plan & usage` is visible to company owners;
other operators retain their ordinary workspace permissions.

Versioned pilot allowances live in `commercial/policy.py`; they are not published
prices. Trial/Standard/Pro currently allow 10/10/50 enabled Field OS members.
Users shared across companies count once in each company. Disabled users do not
count. Native User and Company-permission saves enforce the same seat limit as
the setup wizard. Downgrades do not delete users or business records.

Usage is recorded in an immutable company ledger. A company-row database lock
serializes admission, and a unique hash scopes idempotency to company, metric and
source. Monthly allowances reset on the first day of the site's calendar month.
AI units are successful model responses (including polling classification); email units
are recipients admitted to outbound delivery; SMS units are logical messages,
not carrier segments. Delivery, failures and carrier costs are separate facts.
Repeated native email worker attempts do not consume another admission.

Trial expiry and suspension leave reads, billing recovery, conversation clearing
and rejection available. Mutation APIs enforce subscription status and feature
flags independently of route or model output. Incoming customer messages and
consent changes are never rejected because of a commercial quota. Public webhook intake uses deterministic classification. Polling classification
falls back to the deterministic classifier if AI is unavailable or exhausted.
This does not suspend the underlying ERPNext administrator's accounting access.

Synchronous providers still require a provider-side idempotency guarantee if a
process fails after acceptance but before commit. PR27 addresses durable dispatch
and uncertain outcomes; this ledger alone cannot guarantee exactly-once delivery.

Validation includes isolated policy boundary tests, native MariaDB ledger and
role checks, the owner plan browser flow, and the existing operational suite.
Use the CI result for the reviewed commit as evidence, not this document alone.
