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
Open a customer in Field OS to create equipment, edit its details, and inspect its
parent/component hierarchy and service history. Managers and dispatchers maintain
equipment; technicians add permanent notes, optional service-visit links, and
private JPEG/PNG/WebP photos. Uploads strip image metadata and accept at most 20
photos per note (5 MB and 25 megapixels per photo). Company, customer and site are
fixed after creation; stale edits require a reload.

Native Desk, document REST reads and private attachment access enforce the same
company boundary as the operator APIs. Customer 360 scopes visits, quotations,
invoices and equipment to the selected company, including shared customers.

On a disposable, installed Frappe/ERPNext site, enable `allow_tests` and run
`bench --site test_site execute erpnext.field_os.tests.live_equipment.run` for
real database, role, tenant and attachment checks. This creates explicitly named
integration fixtures and rolls back test mutations. The Field OS workflow also
runs these checks against MariaDB.

## Isolated unit checks

Run `python erpnext/field_os/tests/run_unit.py` from the repository root. Without
Frappe installed, this uses strict import stubs for the boundaries already mocked
by the unit tests. It does not validate site migrations, database transactions,
provider delivery, or browser workflows.
