"""Native read permissions required by ERPNext's quotation calculations."""

import frappe
from frappe.permissions import add_permission


def ensure_native_read_permissions():
	for role in ("Field OS Owner", "Field OS Manager", "Field OS Dispatcher", "Field OS Billing"):
		for doctype, permission in (("Item", "read"), ("Account", "select")):
			if frappe.db.exists("Role", role) and not frappe.db.exists(
				"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}
			):
				add_permission(doctype, role, ptype=permission)
