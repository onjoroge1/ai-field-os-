from hashlib import sha256

import frappe
from frappe.model.document import Document


class FieldOSEmailIntegration(Document):
	def validate(self):
		if not self.provider_factory or "." not in self.provider_factory:
			frappe.throw("Provider Factory must be a Python import path")
		self.mailbox_key_hash = sha256(self.mailbox_key.encode()).hexdigest()
