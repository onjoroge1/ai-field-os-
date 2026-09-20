import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSInboxCorrection(Document):
	def validate(self):
		thread_company = frappe.db.get_value("Field OS Communication Thread", self.thread, "company")
		if thread_company != self.company:
			frappe.throw(_("Correction company must match its Inbox thread"))
		if self.message:
			message_thread = frappe.db.get_value("Field OS Communication Message", self.message, "thread")
			if message_thread != self.thread:
				frappe.throw(_("Correction message must belong to its Inbox thread"))
