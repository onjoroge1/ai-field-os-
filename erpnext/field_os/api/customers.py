"""Customer 360 endpoint."""

from __future__ import annotations

from dataclasses import asdict

import frappe

from erpnext.field_os.customers.communication_timeline import FrappeCustomerCommunicationTimeline
from erpnext.field_os.customers.frappe_access import ERPNextCustomerAccessPolicy
from erpnext.field_os.customers.service import Customer360Service
from erpnext.field_os.equipment.frappe_repository import CompanyCustomerAdapter, FrappeEquipmentRepository
from erpnext.field_os.security.context import resolve_tenant_context


@frappe.whitelist()
def customer_360(company: str, customer_id: str) -> dict[str, object]:
	context = resolve_tenant_context(company)
	view = Customer360Service(
		CompanyCustomerAdapter(company), ERPNextCustomerAccessPolicy(), FrappeCustomerCommunicationTimeline()
	).get(context, customer_id)
	result = asdict(view)
	result["hvac_equipment"] = [
		asdict(item) for item in FrappeEquipmentRepository().list_equipment(company, customer_id)
	]
	return result
