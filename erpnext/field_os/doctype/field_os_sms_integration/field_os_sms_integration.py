import re
from hashlib import sha256

import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSSMSIntegration(Document):
	def validate(self):
		if not self.provider_factory or "." not in self.provider_factory:
			frappe.throw(_("Provider Factory must be a Python import path"))
		self.endpoint_key_hash = sha256(self.endpoint_key.encode()).hexdigest()
		if not re.fullmatch(r"\+[1-9][0-9]{7,14}", (self.from_number or "").strip()):
			frappe.throw(_("From Number must use E.164 format, for example +14045551000"))
