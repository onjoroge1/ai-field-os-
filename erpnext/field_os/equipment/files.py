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
	return "read" in capabilities_for(context)


class EquipmentFile:
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
