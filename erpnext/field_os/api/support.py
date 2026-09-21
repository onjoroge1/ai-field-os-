import frappe

from erpnext.field_os.support import service


@frappe.whitelist()
def grants(company: str) -> list[dict]:
	return service.grants(company)


@frappe.whitelist(methods=["POST"])
def grant(company: str, support_user: str, reason: str, minutes: int = 30) -> list[dict]:
	return service.grant(company, support_user, reason, minutes)


@frappe.whitelist(methods=["POST"])
def revoke(company: str, grant_id: str) -> list[dict]:
	return service.revoke(company, grant_id)


@frappe.whitelist()
def lookup(query: str) -> list[dict]:
	return service.lookup(query)


@frappe.whitelist()
def my_grants() -> list[dict]:
	return service.my_grants()


@frappe.whitelist(methods=["POST"])
def inspect(company: str, grant_id: str = "", reason: str = "") -> dict[str, object]:
	return service.inspect(company, grant_id, reason)


@frappe.whitelist(methods=["POST"])
def set_flags(company: str, disabled: list[str], version: str, reason: str) -> dict[str, object]:
	return service.flags(company, disabled, version, reason)
