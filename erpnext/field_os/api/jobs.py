import frappe

from erpnext.field_os.jobs import service


@frappe.whitelist()
def get_jobs(company: str):
	return service.listing(company)


@frappe.whitelist(methods=["POST"])
def replay(
	company: str, name: str, reason: str, resolution: str | None = None, external_id: str | None = None
):
	return service.replay(company, name, reason, resolution, external_id)
