# Roadmap PR25 — support console

The `/desk/field-os-support` page gives the Field OS Support role bounded tenant
lookup and lists their active owner grants. Owners grant and revoke access from
Plan & usage. Each grant lasts 5–60 minutes, is bound to one support user and one
company, and stops working if it expires, is revoked, the support role is removed,
or the approving owner loses company access. Support never changes session user
and receives no customer message bodies, attachments, integration secrets or raw
provider exceptions. Scope is diagnostics, counts and audit inspection.

System Managers can inspect company diagnostics with an explicit recorded reason
and change allowlisted feature flags with optimistic version checks. That is the
existing administrative trust boundary; support grants do not confer it. Every
grant, revocation, inspection and flag change appends a permanent audit event.
The database remains the trust boundary for privileged infrastructure operators.

Create support users with the Field OS Support role and no Company permissions
or operational Field OS roles. Owners must verify the named support account
before granting access. Staff can inspect errors as status indicators; request a
separate explicit customer action when reproduction requires operating on data.

Validation: native acceptance covers owner consent, different-company rejection,
expiry, revocation, audit immutability and non-admin feature-change rejection.
The cumulative browser flow verifies the owner grant controls.

Native permissions: https://docs.frappe.io/framework/user/en/basics/users-and-permissions
