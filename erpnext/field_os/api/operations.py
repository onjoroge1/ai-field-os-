import frappe

from erpnext.field_os.observability.service import dashboard


@frappe.whitelist()
def get_dashboard(company: str):
	return dashboard(company)
