import frappe
from frappe.model.document import Document


class FieldOSHVACEquipment(Document):
	def validate(self):
		if self.parent_equipment == self.name:
			frappe.throw("Equipment cannot be its own parent")
		if self.parent_equipment:
			parent = frappe.db.get_value(
				"Field OS HVAC Equipment",
				self.parent_equipment,
				["company", "customer", "site"],
				as_dict=True,
			)
			if not parent or (parent.company, parent.customer, parent.site) != (
				self.company,
				self.customer,
				self.site,
			):
				frappe.throw("Parent equipment must belong to the same tenant, customer, and site")
