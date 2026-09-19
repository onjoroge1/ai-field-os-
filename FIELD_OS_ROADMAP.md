# AI Field OS — Production Roadmap

## Product thesis
AI Field OS turns a mature ERP/FSM backend into an AI-native operating system for commercial HVAC contractors. A new dispatcher should be able to complete common work without learning ERP navigation. Complexity stays in the system; the user works from Today, Inbox, Ask, Customers, Jobs, and explicit approval cards.

## Production definition
Production-ready means a commercial HVAC company can be onboarded, import its operating data, receive customer requests through supported communication channels, create/schedule/dispatch jobs, communicate with customers and technicians, manage estimates/invoices, and operate daily through a role-aware AI interface with deterministic permissions, approvals, auditability, observability, backups, recovery, billing, support tooling, and documented security controls.

## Non-negotiable architecture
- ERPNext/Frappe remains the system of record for mature ERP capabilities.
- AI Field OS is a separate product layer; avoid invasive ERPNext core changes.
- All ERP access goes through a typed adapter/service boundary.
- Models never receive direct SQL/database write access.
- AI proposes structured tool calls; policy code authorizes execution.
- External, financial, destructive, or high-impact actions require policy-defined confirmation.
- Every mutation records actor, request, proposal, approval, execution result, and correlation ID.
- Idempotency is mandatory for side effects.
- Tenant isolation and least privilege are mandatory.
- Communications attach to canonical business objects (customer/site/equipment/job/quote/invoice).

## Primary users
1. Owner / operations manager
2. Dispatcher / CSR
3. Field technician
4. Billing / office administrator
5. Customer (limited portal/communications)

## Core experience
### Today
Operational exceptions first: jobs, delays, approvals, unassigned work, ready-to-invoice work, overdue items.

### Inbox
Unified operational queue for email, SMS, web requests, technician notes, and later call transcripts. AI classifies and links each item to business records.

### Ask Operations
Natural-language read and action interface backed only by registered tools.

### Customer / Site / Equipment
A unified timeline containing service history, communications, equipment, quotes, jobs, invoices, and documents.

### Jobs
Request -> triage -> quote/approval where needed -> schedule -> dispatch -> field work -> completion -> invoice -> payment/follow-up.

## Reference architecture
UI -> Field OS API -> Identity/Tenant Context -> AI Orchestrator -> Tool Registry -> Policy/Approval Engine -> ERPNext Adapter -> ERPNext/Frappe

Parallel services:
- Communication ingestion/delivery
- Job/event queue
- Audit ledger
- Observability
- Document/object storage
- Billing/entitlements

## Roadmap / PR sequence

### Phase 0 — Product and engineering contract
**PR 0 — Roadmap, architecture, production definition**
- This roadmap
- Architecture decision record
- domain glossary
- risk/action taxonomy
- explicit MVP and production exit criteria

**Exit:** future PRs can be evaluated against one product contract.

### Phase 1 — Safe ERP boundary
**PR 1 — Field OS extension skeleton**
- Create isolated Field OS module/app boundary inside the fork
- configuration and environment validation
- health/readiness endpoints
- local developer setup
- CI checks for new code
- no secrets in repository

**PR 2 — ERPNext typed adapter**
- customer, address/site, contact, item/equipment mapping
- service request/job primitives
- quote/invoice read primitives
- normalized errors/timeouts/retries
- contract tests against ERPNext

**PR 3 — Tenant, identity, roles and authorization**
- tenant context
- owner/manager/dispatcher/technician/billing roles
- server-side authorization matrix
- tenant isolation tests

**Exit:** application can safely read/write an isolated test tenant through a stable adapter.

### Phase 2 — First magical workflow
**PR 4 — Service request domain + deterministic scheduling**
- request lifecycle
- technician skills/availability abstraction
- scheduling constraints
- conflict detection
- deterministic proposal engine

**PR 5 — AI tool registry + structured intent**
- registered read/action tools
- schema validation
- tool allowlists
- model-provider abstraction
- prompt-injection boundary
- no arbitrary code/SQL execution

**PR 6 — Approval and action engine**
- READ / LOW / EXTERNAL / FINANCIAL / DESTRUCTIVE risk classes
- preview/approve/reject
- idempotency keys
- stale-proposal detection
- execution receipts
- immutable audit events

**PR 7 — Request-to-booking vertical slice**
- parse inbound request
- resolve customer/site/equipment
- retrieve history
- propose slot/technician
- approval card
- create job
- confirmation event
- full E2E test

**Exit:** demo workflow works end-to-end without manual ERP navigation.

### Phase 3 — AI-native operator UI
**PR 8 — App shell + Today**
- responsive role-aware shell
- exception-first Today dashboard
- attention queue
- global search

**PR 9 — Ask Operations**
- conversational command UI
- tool-call preview
- citations/record links in answers
- approval cards
- failure/retry UX
- conversation retention controls

**PR 10 — Customer/site/equipment 360**
- unified timeline
- equipment/service history
- open work/quotes/invoices
- communication context

**PR 11 — Jobs/dispatch workspace**
- schedule/dispatch views
- technician status
- conflicts
- reschedule/reassign flows
- mobile-safe technician workflow

**Exit:** dispatcher can perform core daily work in Field OS rather than ERPNext screens.

### Phase 4 — Communications as operating data
**PR 12 — Communication data model**
- threads/messages/participants/channels
- canonical entity linking
- attachments
- consent/preferences
- delivery states

**PR 13 — Email ingestion and outbound email**
- mailbox/provider integration abstraction
- inbound webhook/poll processing
- threading/deduplication
- AI classification/linking
- draft -> approve -> send
- bounce/error handling

**PR 14 — SMS**
- provider abstraction
- inbound/outbound SMS
- STOP/consent controls
- templates
- delivery receipts
- customer timeline integration

**PR 15 — Unified Inbox**
- triage queue
- suggested actions
- assignment
- SLA/age indicators
- human correction feedback

**Exit:** a request can enter through email/SMS and complete the booking workflow with a complete audit trail.

### Phase 5 — HVAC vertical depth
**PR 16 — HVAC equipment and service history**
- sites, units, model/serial, install date
- equipment hierarchy
- warranty/service metadata
- technician notes/photos

**PR 17 — Estimates, approvals and parts**
- estimate lifecycle
- customer approval
- required parts
- inventory linkage
- approval-aware AI actions

**PR 18 — Maintenance agreements**
- recurring maintenance
- due/overdue visits
- renewal workflow
- agreement dashboards

**PR 19 — Completion-to-invoice**
- technician completion checklist
- signatures/photos
- billable labor/parts
- invoice proposal
- explicit financial approval
- send/follow-up

**Exit:** commercially meaningful HVAC lifecycle is covered from request through billing.

### Phase 6 — Onboarding and migration
**PR 20 — Company setup wizard**
- company/locations/hours
- users/roles
- service types
- skills
- notification defaults
- integration checks

**PR 21 — Import/migration framework**
- CSV import templates
- customers/sites/equipment
- validation/dry run
- rollback/error report
- migration audit

**PR 22 — Demo/sandbox tenant**
- realistic synthetic HVAC company
- resettable demo data
- guided demo scenarios

**Exit:** a pilot customer can be onboarded without engineering editing the database.

### Phase 7 — Commercial SaaS controls
**PR 23 — Plans, entitlements and metering**
- plan definitions
- user/usage limits
- AI/communication metering
- feature flags

**PR 24 — Billing**
- subscription checkout/management
- invoices/payment state
- trial lifecycle
- delinquency handling
- webhook idempotency

**PR 25 — Admin/support console**
- tenant lookup
- integration health
- audit inspection
- safe impersonation/support access with audit
- feature flags
- support diagnostics

**Exit:** product can charge, provision, support, suspend, and restore customers safely.

### Phase 8 — Production hardening
**PR 26 — Security baseline**
- threat model
- secret management
- secure headers/cookies
- rate limits
- CSRF/session controls where applicable
- dependency/security scanning
- file-upload controls
- PII logging policy

**PR 27 — Reliability and async jobs**
- durable queue
- retries/dead-letter handling
- idempotent consumers
- webhook replay protection
- scheduled jobs
- failure dashboards

**PR 28 — Observability**
- structured logs
- traces/correlation IDs
- metrics
- AI tool/action metrics
- alerting
- cost/latency dashboards

**PR 29 — Backup, restore and disaster recovery**
- backup policy
- encrypted backups
- restore test
- RPO/RTO targets
- runbooks

**PR 30 — Performance and scale**
- representative load tests
- query/API budgets
- caching
- pagination
- concurrency tests
- tenant noisy-neighbor tests

**Exit:** defined SLOs and recovery procedures pass production drills.

### Phase 9 — Trust, quality and release
**PR 31 — AI evaluation harness**
- golden workflow dataset
- intent/tool selection tests
- hallucination/unsupported-action tests
- prompt-injection/adversarial tests
- regression gates
- model change evaluation

**PR 32 — E2E and release gates**
- critical-path browser/API tests
- permission tests
- communication sandbox tests
- migration tests
- smoke tests
- release checklist

**PR 33 — Privacy, retention and customer controls**
- retention configuration
- export/delete workflows
- consent records
- audit export
- privacy/security documentation

**PR 34 — Production deployment**
- staging/production separation
- infrastructure/deployment docs
- migration strategy
- rollback
- zero/low-downtime release procedure
- operational runbooks

**Exit:** production release candidate passes security, reliability, AI-eval, migration, E2E, restore and rollback gates.

### Phase 10 — Pilot -> GA
**PR 35 — Pilot instrumentation and feedback**
- onboarding funnel
- time-to-first-job
- AI acceptance/edit/rejection rates
- task completion time
- support telemetry
- product feedback capture

**PR 36 — GA readiness**
- close pilot blockers
- documentation/help center
- support SLAs/process
- pricing/plan configuration
- status/incident process
- final production checklist

## MVP boundary
MVP is reached after PR 15 plus the minimum HVAC domain support needed for a real pilot. It is not GA. MVP proves that a dispatcher can receive an email/SMS request, understand the customer/site/equipment context, get a safe schedule proposal, approve it, create the job, notify the customer, and inspect the entire trail without learning ERPNext navigation.

## GA production gates
All must pass:
- tenant isolation and RBAC tests
- no model/direct DB write path
- 100% mutation audit coverage for Field OS actions
- idempotency for external side effects
- tested backup restore and rollback
- critical E2E workflow suite green
- AI eval thresholds defined and passing
- communication consent/unsubscribe controls verified
- billing and entitlement failure paths tested
- monitoring/alerting/runbooks operational
- pilot migration rehearsed
- documented security/privacy/retention posture
- support/admin tooling usable without database access

## Product success metrics
- median onboarding time
- time to first completed service request
- dispatcher touches per booking
- % requests auto-classified correctly
- % AI proposals approved without edit
- booking cycle time
- communication response time
- jobs requiring ERPNext UI fallback
- invoice-ready lag after completion
- weekly active operators
- support tickets per tenant
- gross margin and AI/communication cost per tenant

## Explicit non-goals for initial GA
- replacing ERPNext accounting
- autonomous refunds/payments
- autonomous high-impact financial/destructive actions
- every home-service vertical
- generalized no-code agent builder
- unrestricted AI database access
- full voice receptionist before email/SMS workflows are reliable
