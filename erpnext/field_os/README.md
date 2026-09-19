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
