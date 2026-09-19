"""Capability checks independent of model output."""

from __future__ import annotations

from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import ROLE_CAPABILITIES


class CapabilityDenied(PermissionError):
	pass


def capabilities_for(context: TenantContext) -> frozenset[str]:
	if context.system_manager:
		return frozenset({"read", "dispatch", "communicate", "quote", "invoice", "field_update", "admin"})
	capabilities: set[str] = set()
	for role in context.roles:
		capabilities.update(ROLE_CAPABILITIES.get(role, ()))
	return frozenset(capabilities)


def authorize(context: TenantContext, capability: str) -> None:
	if capability not in capabilities_for(context):
		raise CapabilityDenied(f"{context.user} is not authorized for capability: {capability}")
