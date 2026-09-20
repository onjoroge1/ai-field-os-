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
`bench --site test_site execute erpnext.field_os.tests.integration.test_equipment_live.run` for
real database, role, tenant and attachment checks. This creates explicitly named
integration fixtures and rolls back test mutations. The Field OS workflow also
runs these checks against MariaDB.

## Estimates
Open **Customer 360 → Estimates → New estimate** to enter labor/parts, quantities,
rates, expiry, customer email and a company tax template. Drafts are native ERPNext
Quotations; Field OS records their approval lifecycle separately. A customer must
have a linked email address and an enabled selling price list in the company's
currency. Stock parts require a warehouse in that company. A fiscal year, outgoing
Email Account and enabled Field OS Email Integration are also required.

**Preview send** shows the exact recipient, total including taxes, and parts
shortages. **Approve and send** submits the quotation and atomically records the
approval and native Email Queue entry. Retries return the recorded result without
queuing another message. Stock availability is informational; sending does not
reserve parts. Ask Operations uses the same server-generated preview and explicit
approval, with current role, actor, company and quotation version checks.

The customer receives a private, expiring link and signs in with an enabled customer
account whose email matches the recipient to review, approve or decline the quote.
Both the private link and that account are required. Create customer portal accounts
through ERPNext's normal user onboarding before using online approvals; customers
without an account can reply to the email. Operators can also record a decision with the
customer's name and confirmation evidence. Decisions are permanent, and a revision
creates a new draft linked to the original. Approval links expire after at most 14
days and reject changed or cancelled quotations.

The native mail worker owns SMTP delivery and retries. Keep the scheduler and queue
workers running. Delivery status appears on the estimate immediately and syncs to
Inbox every 15 minutes. An email queued successfully is shown as **Not Sent** until
the mail worker reports success; queueing alone is not delivery confirmation.

Run `bench --site test_site execute erpnext.field_os.tests.integration.test_estimates_live.run`
on an installed disposable site with `allow_tests=1`. CI also creates an estimate
through the browser, delivers it to a local SMTP capture server, follows the actual
email link as a customer and checks the persisted approval as an operator.

## Agreements
Create a draft under **Customer 360 → Maintenance agreements**, select a linked
service address and enabled non-stock service item, then activate it. Activation
creates the term's recurring obligations once. The first visit is one interval
after the start date, and later due dates stay anchored to the original start,
including month-end dates. Terms are limited to ten years and become permanent
on activation. Pausing stops new scheduling; existing service jobs remain visible.

**Agreements** shows active contracts, visits due within a month, overdue work and
renewals. Schedule an obligation with a company technician to create a native
Maintenance Visit, then manage its assignment in **Dispatch**. A technician needs
an enabled Sales Person linked to an active Employee in the selected company.
Draft service jobs appear as Scheduled; only submitted, fully completed visits
satisfy the obligation. Cancelled jobs can be replaced without duplicating the
recurring obligation. Completed visits never move the next due date.

**Create renewal** produces a separate draft beginning after the current term.
Repeated requests return the same renewal. Review and activate it explicitly;
there is no automatic financial commitment or customer notification. The daily
scheduler expires old contracts while preserving unfulfilled obligations. The
dashboard also computes expiry immediately, without waiting for the scheduler.
Each company dashboard shows up to 500 contracts, with customer-specific views
available from Customer 360.

CI runs `test_agreements_live.run` on MariaDB and a browser flow covering creation,
activation, recurring service job creation, renewal and the company dashboard.

## Isolated unit checks

Run `python erpnext/field_os/tests/run_unit.py` from the repository root. Without
Frappe installed, this uses strict import stubs for the boundaries already mocked
by the unit tests. It does not validate site migrations, database transactions,
provider delivery, or browser workflows.


### Service completion and invoicing

Open **Service work** to capture an assigned visit. A technician saves a work summary, the safety/operation/cleanup checklist, billable service and parts, at least one private photo, and a captured customer signature with the signer's name. **Complete visit** submits the native Maintenance Visit and locks the evidence. The recurring agreement dashboard then shows that obligation as completed.

A manager or billing operator opens the completed work, selects a due date and company tax template, and reviews **Preview invoice**. The preview saves an unsubmitted Sales Invoice; **Approve and post invoice** posts the native accounting and stock movements. Server-bound approvals expire after ten minutes and reject changed work, pricing or invoices. Durable receipts prevent duplicate invoices when an approved request is retried.

Use **Preview invoice email** to review the customer recipient and balance, then explicitly approve sending. Email delivery uses the native outgoing queue and appears in completion history and the unified Inbox. Payment follow-ups also require approval, recheck the balance at send time, and are blocked for paid invoices. Delivery is never triggered automatically by completion or invoicing.

Technicians can access only their assigned jobs and private evidence. Native record access and file downloads enforce both company and assignment. Completed evidence and its files cannot be rewritten or deleted. Corrections to posted invoices continue through ERPNext's native accounting cancellation/credit workflows.


### Company setup wizard

Owners open **Company setup** to save office locations, business days/hours, team accounts and roles, service types with required skills, and notification defaults. System managers can create a new native company from the same screen. Hours use the site's displayed time zone. Technician accounts create native Employee and Sales Person records; provide the employee fields requested by ERPNext and share the initial password directly. The wizard does not send invitations. Only accounts created through this company's setup can be edited here; existing or shared accounts remain under the system administrator.

Service types create native non-stock Items restricted to this company and prices in its own selling price list. Company setup does not alter global price lists. Customer-specific price lists continue to take precedence. Once setup is completed, Dispatch and agreement scheduling enforce the configured hours and service skills.

**Run checks** verifies saved steps, native financial defaults, a dispatch technician, service skill coverage and the preferred channel's sending configuration. Choose None if a communication channel is not yet connected. Email/SMS credentials are configured through their native integration settings by the system administrator. Configuration checks do not claim to prove provider delivery; delivery history is recorded after an explicitly approved message. Default email sender and invoice due days prefill estimates and billing.

## PR21: CSV migration

Owners open **Data import**, download a template, and import customers → sites →
equipment. External IDs are unique per company and import type; references use
those IDs, not global ERPNext names. Sites use the company's configured country.
Each upload accepts up to 1000 rows / 2 MB. A dry run stores validation results
without creating business records. Review all rows (Show more rows for large
files), download the error report, then explicitly apply the import.

Imports create company-restricted native Customers and Contacts, customer-linked
Addresses, and HVAC Equipment. Existing records are never overwritten. Native
validation failures roll back the entire batch and retain an error audit. Repeating
Apply returns the existing receipt without duplicating records.

**Preview rollback** lists every record to remove. Approval is bound to the owner,
company and batch version and expires after ten minutes. Rollback preserves changed
records, new comments, attachments and native document dependencies. Roll back
equipment before sites, and sites before customers. The import audit and durable
retry receipt remain after removal. Imported customers are searchable immediately,
including before their first service transaction.

Verification: isolated regression suite plus `test_migrations_live.run` on a native
Frappe site and `test_migrations_browser.py` in the hosted MariaDB acceptance job.
The browser flow imports all three CSVs, opens the equipment through Customer 360,
and explicitly approves each rollback.

Native import reference: https://docs.frappe.io/erpnext/data-import

## PR22: guided HVAC demo

A system administrator opens **Demo guide → Create demo company**, chooses a
company label and a demo login password, and receives a new isolated native ERPNext
company. The guide lists the synthetic owner and technician logins. It contains
three customers/sites/equipment units, service history, an urgent no-cooling Inbox
request, a planned diagnostic visit, overdue recurring maintenance and a sample
approved estimate. Approval evidence explicitly identifies the synthetic seed.
The guide opens the real Inbox, Customer 360, Dispatch, agreement, estimate and
service-work screens. The shell labels the company as a synthetic demo throughout.

All Field OS email/SMS sends are blocked for registered demo companies, and native
reference-linked Email Queue insertion is guarded as well. No real mailbox or
provider credentials are configured. The demo estimate integration supports local
preparation only. Invoice posting remains native accounting inside the demo company.

**Preview demo reset** explains the exact effect before approval: provision a fresh
company generation, archive the old generation, and disable its two synthetic
logins. Records and posted financial entries are retained in the archived company;
reset never cancels, deletes or rewrites them. Set the new generation's login
password, approve, and the guide switches to the fresh company. Reset requires a
system administrator because it provisions a new tenant. Production companies
cannot be registered retroactively or reset through this API. Audit/version-bound
approvals and durable receipts prevent duplicate reset generations after retries.

Native `test_demo_live.run` verifies dataset persistence, tenant permissions,
communication blocking and reset after an actual posted invoice, including receipt
replay after cache loss. The hosted browser flow provisions a demo, opens its
synthetic Inbox, overdue agreement and approval evidence, then explicitly resets.
