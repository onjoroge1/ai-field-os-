"""Frappe configuration, contact resolution, and templates for SMS."""

from __future__ import annotations

from dataclasses import dataclass

import frappe

from erpnext.field_os.communications.models import CommunicationChannel, EntityLinks
from erpnext.field_os.communications.service import normalize_address
from erpnext.field_os.communications.sms import SMSProvider, SMSTemplate
from erpnext.field_os.customers.frappe_access import ERPNextCustomerAccessPolicy


@dataclass(frozen=True, slots=True)
class SMSIntegration:
	id: str
	company: str
	endpoint_key: str
	from_number: str
	provider: SMSProvider
	webhook_secret: str
	poll_cursor: str | None = None


class FrappeSMSEntityResolver:
	def __init__(self) -> None:
		self.access = ERPNextCustomerAccessPolicy()

	def resolve(self, company: str, sender_number: str) -> EntityLinks:
		normalized = normalize_address(CommunicationChannel.SMS, sender_number)
		contact_names = set()
		# Contact phone values are not consistently normalized in legacy ERP data,
		# so compare normalized values from a bounded candidate set.
		for row in frappe.get_all(
			"Contact Phone", fields=["parent", "phone"], order_by="modified desc", limit=1000
		):
			if normalize_address(CommunicationChannel.SMS, row.phone or "") == normalized:
				contact_names.add(row.parent)
		if not contact_names:
			return EntityLinks()
		customer_ids = frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "Contact",
				"parent": ["in", list(contact_names)],
				"link_doctype": "Customer",
			},
			pluck="link_name",
			distinct=True,
			limit=20,
		)
		for customer_id in customer_ids:
			if self.access.can_access(company, customer_id):
				return EntityLinks(customer_id=customer_id)
		return EntityLinks()


def load_sms_integration(
	*, integration_id: str | None = None, endpoint_key: str | None = None
) -> SMSIntegration:
	if bool(integration_id) == bool(endpoint_key):
		raise ValueError("Provide exactly one SMS integration identifier")
	filters = {"enabled": 1}
	if integration_id:
		filters["name"] = integration_id
	else:
		filters["endpoint_key"] = endpoint_key
	name = frappe.db.get_value("Field OS SMS Integration", filters, "name")
	if not name:
		raise ValueError("Enabled SMS integration was not found")
	doc = frappe.get_doc("Field OS SMS Integration", name)
	provider_factory = frappe.get_attr(doc.provider_factory)
	return SMSIntegration(
		doc.name,
		doc.company,
		doc.endpoint_key,
		doc.from_number,
		provider_factory(),
		doc.get_password("webhook_secret"),
		doc.poll_cursor,
	)


def load_sms_template(company: str, template_id: str) -> SMSTemplate:
	doc = frappe.get_doc("Field OS SMS Template", template_id)
	if doc.company != company or not doc.enabled:
		raise PermissionError("SMS template is not enabled for this tenant")
	variables = frozenset(item.strip() for item in (doc.variables or "").split(",") if item.strip())
	return SMSTemplate(doc.name, doc.body, variables, bool(doc.transactional))
