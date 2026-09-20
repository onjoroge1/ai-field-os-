import json

from frappe.model.document import Document


class FieldOSOnboarding(Document):
	def validate(self):
		for field in (
			"completed_steps_json",
			"company_json",
			"users_json",
			"services_json",
			"notifications_json",
		):
			if self.get(field):
				json.loads(self.get(field))
