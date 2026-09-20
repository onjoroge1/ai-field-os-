# AI Field OS extension

This namespace contains the AI-native field-service product layer.

## Boundary rules
1. Do not add direct model/database writes from LLM code.
2. ERPNext access belongs behind `field_os.adapter`.
3. Side effects must pass the policy/approval layer once introduced.
4. New code must remain tenant-aware and auditable.
5. Secrets are supplied at runtime; never commit credentials.

## Initial environment
- `FIELD_OS_ENABLED=false`
- `FIELD_OS_ENVIRONMENT=development|test|staging|production`
- `FIELD_OS_MODEL_PROVIDER=disabled`
- `FIELD_OS_REQUIRE_ACTION_APPROVAL=true`

Production fails validation if action approvals are disabled.

## Operator workspace

After migrating the site, open `/app/field-os`. The role-aware shell resolves
an explicit company tenant and starts on an exception-first Today queue. All
search and dashboard reads are company-scoped on the server.

Ask Operations is vendor-neutral. Set `FIELD_OS_MODEL_PROVIDER` to a Python
factory import path that implements `ModelProvider`; `disabled` fails closed.
Conversation retention can be disabled, limited to the session, or set to 30
days. Tool citations are created from server results, never accepted from model
text.

## Email

Create a **Field OS Email Integration** for each tenant mailbox. Inbound and
delivery webhooks use an HMAC-SHA256 signature and resolve the tenant from the
opaque mailbox key; callers cannot choose a company. Provider adapters may also
poll every 15 minutes. Outbound email always follows draft -> preview -> explicit
approval -> send, with delivery failures retained on the message for retry.

## SMS

Create a **Field OS SMS Integration** for each tenant number. SMS uses the same
signed webhook, deduplication, approval, polling, and delivery-state model as
email. STOP-family keywords immediately block every outbound SMS; START-family
keywords restore opt-in. Marketing requires explicit opt-in, while transactional
templates may send to an unknown preference but never after an opt-out.

## Unified Inbox

The **Inbox** workspace combines tenant-scoped email, SMS, web, and technician
messages into one triage queue. Open and pending conversations are ordered by
SLA state and age, with filters for channel and assignment. Operators can assign
or close threads, correct classifications and customer links, create a service
request, and reply through the existing approved email/SMS delivery flows.

Corrections are recorded in **Field OS Inbox Correction** so operator feedback
can be used by the later AI evaluation work without silently changing model
behavior. Overdue and unassigned conversations also surface on **Today**.

## HVAC equipment
Tenant-scoped equipment adds sites, hierarchy, model/serial, installation and warranty metadata, plus technician notes and photos.

## Estimates
Estimate sending is approval-gated, parts availability is surfaced, and customer decisions are audited.

## Agreements
Recurring maintenance derives due and overdue visits and identifies renewal windows.

## Completion to invoice
Technician evidence is required before an explicitly approved financial action can create an invoice.

## Onboarding
The owner wizard covers locations/hours, users/roles, services/skills, notification defaults, and integration checks.

## Migrations
CSV templates run through dry-run validation, row errors, audited apply manifests, and approval-gated rollback.
