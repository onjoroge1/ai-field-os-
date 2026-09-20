# PR16–22 integration readiness

The current PRs provide domain services, repository interfaces, DocTypes, and
isolated tests. They are not yet end-to-end pilot workflows. The earlier statement
that this roadmap phase was implemented overstated what the branches contain.

## Delivery work still needed

| Roadmap PR | GitHub PR | Remaining implementation |
| --- | --- | --- |
| 16 | #18 | Frappe equipment/history repository, authenticated API, Customer 360 equipment views, private attachment access, live tenant checks. |
| 17 | #19 | Quotation and stock adapters, actual estimate delivery, persisted customer decisions, operator approval UI. |
| 18 | #20 | Agreement repository, recurring visit creation, renewal actions and dashboard UI. |
| 19 | #21 | Completion persistence, atomic Sales Invoice creation, invoice send/follow-up, technician and billing screens. |
| 20 | #22 | Company/location/hours/user/service writes, integration probes, setup wizard. |
| 21 | #23 | Transactional imports and rollback, customer/site/equipment relational validation, durable audit, upload and error-report UI. |
| 22 | #24 | Synthetic HVAC dataset, transactional seed/reset repository, guided demo screens. |

Abstract repository contracts are not live integrations. For example, estimate
send currently delegates a status update; invoice creation, import, rollback,
seed, and reset all rely on repository methods without production implementations.
The action engine's receipt cache is process-local; database-backed adapters must
prevent duplicate external effects across workers and restarts before those paths
are exposed to operators.

## Corrections in this review

- Recheck current capabilities when executing estimates, invoices, rollback, and
  demo reset. Bind proposals to tenant, actor, operation, and risk.
- Check source status/version at execution and reject changed rollback/reset
  manifests. Keep successful same-key retries idempotent within the action engine.
- Reject hierarchy cycles and cross-site relationships; validate note ownership.
- Reject invalid maintenance intervals, billable amounts, incomplete integration
  checks, and malformed CSV columns/rows.
- Translate Frappe validation messages reported by Semgrep.

## Validation boundary

The combined stack has 100 passing isolated unit tests under Python 3.12. Run
`python erpnext/field_os/tests/run_unit.py`. The strict Frappe import stubs fail any
unmocked framework access. Ruff, compilation, and JSON checks complement these
tests. Live Frappe/database, site migration, and browser checks still require a
configured environment; those checks are necessary before a pilot release.

## Landing order

Integration PR #25 must land in `develop` first. It still has a Semgrep security
review requirement for the four public signed email/SMS webhook handlers. This
review does not suppress that rule or change workflow protection.

After #25 passes its gates and is merged, retarget #18 to `develop`. Merge with a
regular merge commit, then retarget #19, and continue through #24. Keep later PRs
based on their predecessor until that predecessor lands. This preserves ancestry
and prevents another stack that is marked merged without reaching `develop`.
