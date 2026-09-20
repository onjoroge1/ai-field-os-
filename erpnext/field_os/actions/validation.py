"""Bind a saved approval to the current actor, tenant, operation, and risk."""

from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.security.context import TenantContext


def require_proposal(
	proposal: ActionProposal | None,
	context: TenantContext,
	*,
	tool: str,
	risk: RiskClass,
) -> ActionProposal:
	if (
		proposal is None
		or proposal.company != context.company
		or proposal.actor != context.user
		or proposal.tool != tool
		or proposal.risk != risk
	):
		raise ValueError("Approval does not match this actor, tenant, and operation")
	return proposal
