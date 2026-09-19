# ADR-0001: AI Field OS product boundary

**Status:** Accepted

## Decision
ERPNext/Frappe is the initial system of record. AI Field OS owns the simplified operator experience, AI orchestration, policy/approval controls, communications, audit semantics, and vertical HVAC workflows.

We will avoid making AI behavior depend on direct database access or arbitrary ERPNext internals. ERP operations are exposed to AI Field OS through a typed adapter and a registered tool catalog.

## Why
The business advantage is not rebuilding accounting, inventory, CRM, or generic ERP. It is making mature operational software dramatically easier and safer to operate. Keeping a boundary also lets the same AI Operations layer later target another ERP/TMS/property system or an acquired vertical SaaS.

## Action safety
- Read-only queries may execute when authorized.
- External communication requires policy evaluation and can require confirmation.
- Financial and destructive mutations require explicit confirmation by an authorized user.
- Every mutation is idempotent where possible and produces an audit receipt.
- Model output is untrusted input until schema and policy validation pass.

## Consequences
- Some ERPNext screens remain available as an escape hatch during early releases.
- Adapter maintenance is a first-class responsibility.
- UI/product code should not import ERPNext persistence internals directly.
- Model providers can change without changing the action contract.
