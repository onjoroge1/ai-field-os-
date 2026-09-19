from hashlib import sha256

from frappe.model.document import Document


class FieldOSContactPreference(Document):
	def validate(self):
		self.preference_key = sha256(
			f"{self.company}\0{self.channel}\0{self.contact_address}".encode()
		).hexdigest()
