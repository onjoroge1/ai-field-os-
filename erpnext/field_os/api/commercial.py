"""Owner plan and usage view. Plan assignment is controlled by the billing service."""

import frappe

from erpnext.field_os.commercial.native import summary


@frappe.whitelist()
def get_plan(company: str) -> dict[str, object]:
	return summary(company)
