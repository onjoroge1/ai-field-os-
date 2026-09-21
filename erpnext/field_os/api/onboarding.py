"""Company setup endpoints; only explicit tenant owners and system managers may mutate."""

import frappe
from frappe import _
from frappe.utils import get_system_timezone

from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.onboarding import native


@frappe.whitelist()
def get_setup(company: str):
	ctx = native.context(company)
	return {
		**native.state(company),
		"checks": native.checks(company),
		"system_manager": ctx.system_manager,
		"country": frappe.db.get_value("Company", company, "country"),
		"currency": frappe.db.get_value("Company", company, "default_currency"),
		"timezone": get_system_timezone(),
		"genders": sorted(
			set(frappe.get_all("Gender", pluck="name"))
			| {"Female", "Male", "Non-binary", "Prefer not to say"}
		),
		"email_integrations": frappe.get_all(
			"Field OS Email Integration",
			filters={"company": company, "enabled": 1},
			fields=["name", "from_address"],
		),
		"sms_integrations": frappe.get_all(
			"Field OS SMS Integration",
			filters={"company": company, "enabled": 1},
			fields=["name", "from_number"],
		),
	}


@frappe.whitelist(methods=["POST"])
@entitled
def save_step(company: str, step: str, values: dict | list | str, version: str):
	ctx = native.context(company)
	method = {
		"company": native.save_company,
		"users": native.save_user,
		"services": native.save_services,
		"notifications": native.save_notifications,
	}.get(step)
	if not method:
		frappe.throw(_("Choose a valid setup step"))
	return method(ctx, values, version)


@frappe.whitelist(methods=["POST"])
@entitled
def complete(company: str, version: str):
	return native.complete(native.context(company), version)


@frappe.whitelist(methods=["POST"])
def create_company(name: str, abbreviation: str, country: str, currency: str):
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("A system administrator must create the company tenant"), frappe.PermissionError)
	name = native.text(name, "company name", 80)
	abbreviation = native.text(abbreviation, "company abbreviation", 5)
	if (
		not abbreviation.isalnum()
		or not frappe.db.exists("Country", country)
		or not frappe.db.exists("Currency", currency)
	):
		frappe.throw(_("Choose a valid abbreviation, country and currency"))
	if frappe.db.exists("Company", name):
		frappe.throw(_("This company already exists"))
	doc = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"abbr": abbreviation,
			"country": country,
			"default_currency": currency,
			"chart_of_accounts": "Standard",
		}
	).insert()
	doc.update_default_account = 1
	doc.set_default_accounts()
	frappe.clear_document_cache("Company", doc.name)
	return {"company": doc.name}
