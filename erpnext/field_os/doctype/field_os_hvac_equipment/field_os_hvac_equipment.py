import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from erpnext.field_os.customers.frappe_access import ERPNextCustomerAccessPolicy
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context


class FieldOSHVACEquipment(Document):
	def validate(self):
		authorize(resolve_tenant_context(self.company), "dispatch")
		previous = self.get_doc_before_save()
		if previous and any(self.get(key) != previous.get(key) for key in ("company", "customer", "site")):
			frappe.throw(_("Equipment company, customer and site cannot be changed"))
		if not ERPNextCustomerAccessPolicy().can_access(self.company, self.customer):
			frappe.throw(_("Customer is not available in this company"), frappe.PermissionError)
		if not frappe.db.exists(
			"Dynamic Link",
			{
				"parent": self.site,
				"parenttype": "Address",
				"link_doctype": "Customer",
				"link_name": self.customer,
			},
		):
			frappe.throw(_("Site must be an address linked to this customer"))
		if (
			self.installed_on
			and self.warranty_expires_on
			and getdate(self.warranty_expires_on) < getdate(self.installed_on)
		):
			frappe.throw(_("Warranty expiry cannot be earlier than installation"))
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
