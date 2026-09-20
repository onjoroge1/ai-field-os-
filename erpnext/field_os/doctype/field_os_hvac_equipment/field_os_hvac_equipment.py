import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSHVACEquipment(Document):
	def validate(self):
		parent_id = self.parent_equipment
		seen = {self.name}
		while parent_id:
			if parent_id in seen:
				frappe.throw(_("Equipment hierarchy cannot contain a cycle"))
			seen.add(parent_id)
			parent = frappe.db.get_value(
				"Field OS HVAC Equipment",
				parent_id,
				["company", "customer", "site", "parent_equipment"],
				as_dict=True,
			)
			if not parent or (parent.company, parent.customer, parent.site) != (
				self.company,
				self.customer,
				self.site,
			):
				frappe.throw(_("Parent equipment must belong to the same tenant, customer, and site"))
			parent_id = parent.parent_equipment
