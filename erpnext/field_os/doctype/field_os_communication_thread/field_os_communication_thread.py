from hashlib import sha256

import frappe
from frappe.model.document import Document


class FieldOSCommunicationThread(Document):
	def validate(self):
		if self.external_thread_id:
			self.external_thread_key = sha256(
				f"{self.company}\0{self.channel}\0{self.external_thread_id}".encode()
			).hexdigest()
			duplicate = frappe.db.get_value(
				self.doctype,
				{
					"company": self.company,
					"channel": self.channel,
					"external_thread_id": self.external_thread_id,
					"name": ["!=", self.name or ""],
				},
				"name",
			)
			if duplicate:
				frappe.throw("External thread ID already exists for this company and channel")
		else:
			self.external_thread_key = None
