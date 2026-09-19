from erpnext.field_os.actions.models import RiskClass

CONFIRMATION_REQUIRED = frozenset({RiskClass.EXTERNAL, RiskClass.FINANCIAL, RiskClass.DESTRUCTIVE})


def requires_confirmation(risk: RiskClass) -> bool:
	return risk in CONFIRMATION_REQUIRED
