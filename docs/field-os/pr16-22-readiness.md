# PR16–22 implementation and acceptance

The original stacked PRs #18–24 contained foundation contracts. Completion PRs
#26–32 add the native repositories, authenticated APIs and operator workflows.
They target develop and must land in roadmap order after the preceding PR passes
its gates.

| Roadmap PR | Completion PR | Delivered workflow | Native acceptance module |
| --- | --- | --- | --- |
| 16 | #26 | Equipment hierarchy, history, notes and private photos in Customer 360 | test_equipment_live |
| 17 | #27 | Native quotations, parts, approved email delivery and persisted customer decisions | test_estimates_live |
| 18 | #28 | Recurring obligations, dispatch jobs, renewals and agreement dashboards | test_agreements_live |
| 19 | #29 | Assigned technician evidence, native invoice/stock/accounting and approved delivery/follow-up | test_completions_live |
| 20 | #30 | Native company provisioning, locations/hours, team accounts, services/skills and readiness | test_onboarding_live |
| 21 | #31 | CSV dry run, atomic native import, per-company IDs, error report and protected rollback | test_migrations_live |
| 22 | #32 | Synthetic HVAC company, real guided scenarios and fresh-generation reset | test_demo_live |

## Verification gates

Run `python erpnext/field_os/tests/run_unit.py` for the isolated suite. The Field OS
workflow installs ERPNext on a disposable MariaDB site and runs the native modules
above under `erpnext.field_os.tests.integration`, followed by real browser flows.
Estimate and invoice browser checks deliver through a local SMTP capture server;
they verify the actual message and the customer/operator state. Native invoice
tests verify ledger and stock effects and paid-invoice follow-up rejection.

Browser screenshots are preserved per workflow. Lint, Semgrep, documentation,
semantic commits and the repository patch/migration workflow remain enabled.
Local SQLite verification complements but does not replace MariaDB accounting
and browser acceptance. The legacy upstream self-hosted Server (Mariadb) workflow
may queue separately from the hosted Field OS native acceptance job.

## Operational boundaries

Onboarding checks native financial and sending configuration; it does not claim
that provider credentials have delivered a message. Configure real email/SMS
integrations through their supported provider settings and confirm approved pilot
delivery. Imported sites use the company's country; imports create records rather
than overwriting legacy matches. Rollback is deliberately refused after new use,
attachments, comments or linked operating records.

Demo reset provisions a fresh company and archives the previous generation. Its
posted invoices and ledger remain intact; its synthetic logins are disabled.
Demo external email/SMS is blocked. This is an operator sandbox, not production
seed data, and only system administrators may provision/reset tenant generations.

The later commercialization and production-hardening roadmap phases remain
separate work. Passing these gates completes this roadmap slice, not the later GA
or production deployment milestones.
