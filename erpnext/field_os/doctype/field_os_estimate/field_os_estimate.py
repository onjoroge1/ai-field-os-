import frappe
from frappe import _
from frappe.model.document import Document


class FieldOSEstimate(Document):
	def validate(self):
		quote = frappe.db.get_value(
			"Quotation", self.quotation, ["company", "quotation_to", "party_name"], as_dict=True
		)
		if not quote or (quote.company, quote.quotation_to, quote.party_name) != (
			self.company,
			"Customer",
			self.customer,
		):
			frappe.throw(_("Estimate must reference a customer quotation in the same company"))
		previous = self.get_doc_before_save()
		if previous and (previous.company, previous.customer, previous.quotation) != (
			self.company,
			self.customer,
			self.quotation,
		):
			frappe.throw(_("Estimate ownership cannot be changed"))
