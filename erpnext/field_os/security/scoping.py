"""Helpers that force ERP queries to carry tenant scope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from erpnext.field_os.security.context import TenantContext


def with_company_scope(context: TenantContext, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
	"""Return a new filter dictionary pinned to the authorized tenant.

	Callers cannot override the company selected in the authenticated context.
	"""
	scoped = dict(filters or {})
	requested = scoped.get("company")
	if requested is not None and requested != context.company:
		raise PermissionError("Cross-tenant company filter rejected")
	scoped["company"] = context.company
	return scoped
