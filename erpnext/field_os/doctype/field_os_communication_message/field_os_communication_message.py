from hashlib import sha256

import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSCommunicationMessage(Document):
	def validate(self):
		thread_company = frappe.db.get_value("Field OS Communication Thread", self.thread, "company")
		if thread_company != self.company:
			frappe.throw(_("Message company must match its communication thread"))
		self.dedupe_key_hash = (
			sha256(f"{self.company}\0{self.dedupe_key}".encode()).hexdigest() if self.dedupe_key else None
		)
		self.external_id_hash = (
			sha256(
				f"{self.company}\0{self.channel}\0{self.provider or ''}\0{self.external_id}".encode()
			).hexdigest()
			if self.external_id
			else None
		)
