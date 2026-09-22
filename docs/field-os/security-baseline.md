# Roadmap PR26 — security baseline

## Trust boundaries and threats

| Boundary | Threat | Enforced control |
| --- | --- | --- |
| Operator to company | Forged company IDs, revoked access | Explicit membership and role checks at API and document/file boundaries |
| Model to actions | Prompt injection, arbitrary tools, approval forgery | Registered schemas, independent capabilities and actor/company-bound approvals |
| Provider to webhook | Forged, oversized or replayed events | Provider signatures, request-size budgets, billing timestamp tolerance and durable event receipts |
| Owners to commercial state | Free plan escalation, quota races | Read-only subscription documents, server price catalog, serialized ledger admission |
| Staff to company | Invisible impersonation or lasting access | Named owner grant, one-hour maximum, no session impersonation, immutable inspection audit |
| Upload to file storage | Public evidence, cross-company copies | Private File enforcement, tenant checks after membership revocation, metadata-stripped raster photos |
| Browser to authenticated mutations | CSRF, cached sensitive responses, framing | Native Frappe session/CSRF, POST mutations, no-store, deny framing, secure production session cookies |

The HTTP hook covers both v1/v2 Field OS method routes and legacy `cmd` dispatch.
Limits are 300 requests/minute per authenticated identity and 120/minute per guest
source address, across Field OS endpoints. Redis admission is atomic and expires
old buckets. Loss of Redis rejects requests instead of silently removing limits.
The reverse proxy must also enforce body/time/concurrency budgets; the application
hook runs after Frappe parses the body. Upload/import bodies are capped at 8 MiB;
other Field OS request bodies are capped at 1 MiB.

## Deployment configuration

Set `FIELD_OS_ENVIRONMENT=production`; disable native `developer_mode` and
`ignore_csrf`. Terminate HTTPS at a trusted reverse proxy, configure its forwarded
headers explicitly and set canonical `host_name`. The application marks session
cookies Secure/HttpOnly/SameSite=Lax and sends HSTS in production. Framing,
object embedding and cross-origin base URLs are denied. Frappe uses inline assets;
the CSP deliberately does not claim a strict script policy. A nonce-based script
policy needs framework-wide validation before deployment.

Use separate secret-manager entries per site and environment for Frappe's
encryption key, Stripe, model and communication credentials. Restrict integration
configuration to System Managers, rotate credentials after access changes, and
test rotation in staging. Never put keys in source, links, browser storage or
support notes. Backup encryption keys are handled separately under PR29.

Logs and audit must exclude prompts, message bodies, file bytes, approval links,
passwords, raw provider payloads and authorization headers. Use error categories
and a server-issued correlation ID. Native ERPNext logging is a separate surface;
configure infrastructure log access and retention, and audit it before GA.

## Verification and remaining gates

CI runs Frappe's Semgrep rules, repository lint, permission/file acceptance and
dependency auditing against the installed Frappe/ERPNext test runtime. Native
browser acceptance checks CSRF protection, response headers and role isolation.
Signed public webhook additions retain the repository's manual security-review
requirement. Do not suppress those findings to land a release.

PR27 adds durable processing and replay controls to existing communications;
PR31 supplies the broader adversarial AI evaluation suite; PR33 owns retention
and export/delete. This baseline is not a completed penetration test or GA claim.

Framework security: https://docs.frappe.io/framework/user/en/basics/users-and-permissions
