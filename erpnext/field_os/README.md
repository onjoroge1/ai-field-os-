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
