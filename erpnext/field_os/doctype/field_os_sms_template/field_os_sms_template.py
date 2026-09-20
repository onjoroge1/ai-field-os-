import re

import frappe
from frappe import _
from frappe.model.document import Document

_TOKEN = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*}}")


class FieldOSSMSTemplate(Document):
	def validate(self):
		discovered = set(_TOKEN.findall(self.body or ""))
		declared = {item.strip() for item in (self.variables or "").split(",") if item.strip()}
		if discovered != declared:
			frappe.throw(_("Variables must exactly match the {{variable}} tokens used in Body"))
		if len(self.body or "") > 1600:
			frappe.throw(_("SMS template body cannot exceed 1,600 characters"))
