"""Keep equipment photos private even after the uploader loses company access."""

import frappe
from frappe import _
from frappe.utils import cint

from erpnext.field_os.security.authorization import capabilities_for
from erpnext.field_os.security.context import TenantAccessDenied, resolve_tenant_context

PROTECTED = {"Field OS HVAC Equipment", "Field OS Equipment Note"}


def file_permission(doc, ptype=None, user=None, **kwargs):
	if doc.attached_to_doctype not in PROTECTED:
		return True
	company = frappe.db.get_value(doc.attached_to_doctype, doc.attached_to_name, "company")
	try:
		context = resolve_tenant_context(company, user)
	except TenantAccessDenied:
		return False
	capability = (
		"read" if ptype in (None, "read", "select", "print", "email", "report", "export") else "field_update"
	)
	return capability in capabilities_for(context)


class EquipmentFile:
	def validate_private_file_access(self):
		# Copying an existing blob must not revive an uploader's revoked access.
		if self.file_url:
			existing = frappe.get_all(
				"File",
				filters={"file_url": self.file_url},
				fields=["attached_to_doctype", "attached_to_name"],
			)
			protected = [row for row in existing if row.attached_to_doctype in PROTECTED]
			if protected and not any(file_permission(row, "read") for row in protected):
				frappe.throw(_("Equipment photo is not available in your companies"), frappe.PermissionError)
		super().validate_private_file_access()

	def is_downloadable(self):
		# Frappe's downloader calls File.is_downloadable directly and otherwise allows
		# the original uploader unconditionally, including after membership revocation.
		return file_permission(self, "read") and super().is_downloadable()

	def validate(self):
		previous = self.get_doc_before_save()
		if previous and previous.attached_to_doctype in PROTECTED:
			if (self.attached_to_doctype, self.attached_to_name) != (
				previous.attached_to_doctype,
				previous.attached_to_name,
			):
				frappe.throw(_("Equipment photos cannot be moved to another record"))
		if self.attached_to_doctype in PROTECTED and not cint(self.is_private):
			frappe.throw(_("Equipment photos must remain private"))
		super().validate()
