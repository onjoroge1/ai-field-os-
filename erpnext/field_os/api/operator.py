"""Whitelisted endpoints for the Field OS operator shell."""

from __future__ import annotations

from dataclasses import asdict

import frappe

from erpnext.field_os.operations.frappe_repository import FrappeOperationsRepository
from erpnext.field_os.operations.service import OperationsService
from erpnext.field_os.security.authorization import capabilities_for
from erpnext.field_os.security.context import resolve_tenant_context


def _navigation(capabilities: frozenset[str]) -> list[dict[str, str]]:
	items = [
		("today", "Today", "read"),
		("ask", "Ask Operations", "read"),
		("customers", "Customers", "read"),
		("dispatch", "Dispatch", "dispatch"),
		("agreements", "Agreements", "read"),
		("work", "Service work", "read"),
		("inbox", "Inbox", "communicate"),
		("setup", "Company setup", "admin"),
	]
	return [
		{"id": item_id, "label": label} for item_id, label, capability in items if capability in capabilities
	]


@frappe.whitelist()
def bootstrap(company: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	capabilities = capabilities_for(context)
	return {
		"company": context.company,
		"user": context.user,
		"roles": sorted(role.value for role in context.roles),
		"capabilities": sorted(capabilities),
		"navigation": _navigation(capabilities),
	}


@frappe.whitelist()
def today(company: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	snapshot = OperationsService(FrappeOperationsRepository()).today(context)
	return asdict(snapshot)


@frappe.whitelist()
def global_search(company: str, query: str, limit: int = 20) -> list[dict[str, object]]:
	context = resolve_tenant_context(company)
	results = OperationsService(FrappeOperationsRepository()).search(context, query, limit=int(limit))
	return [asdict(result) for result in results]
