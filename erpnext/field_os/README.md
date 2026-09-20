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
Equipment DocTypes and service contracts cover sites, hierarchy, model/serial,
installation and warranty metadata, plus technician notes and photo references.
The live repository, operator API, and Customer 360 equipment UI remain to be wired.

## Estimates
Estimate service contracts support approval previews, parts shortages, and customer
decisions. Commit rechecks permission, proposal identity, and record version.
ERPNext quotation/stock adapters, delivery, the decision audit writer, and UI are
still required; the current service changes a status through an abstract repository.

## Agreements
Agreement service logic derives due and overdue visits and upcoming renewal windows.
Live persistence, recurring job creation, renewal actions, and dashboard UI remain
to be implemented.

## Isolated unit checks

Run `python erpnext/field_os/tests/run_unit.py` from the repository root. Without
Frappe installed, this uses strict import stubs for the boundaries already mocked
by the unit tests. It does not validate site migrations, database transactions,
provider delivery, or browser workflows.
