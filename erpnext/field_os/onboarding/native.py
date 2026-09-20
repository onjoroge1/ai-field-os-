"""Owner-controlled company setup with native records and operational configuration."""

import json
from datetime import time
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import getdate, validate_email_address

from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import _allowed_companies, resolve_tenant_context
from erpnext.field_os.security.roles import FieldOSRole

DOCTYPE = "Field OS Onboarding"
STEPS = ("company", "users", "services", "notifications")


def context(company):
	ctx = resolve_tenant_context(company)
	authorize(ctx, "admin")
	return ctx


def config(company, field):
	value = frappe.db.get_value(DOCTYPE, {"company": company}, field + "_json")
	return frappe.parse_json(value) if value else ([] if field in {"users", "services"} else {})


def state(company):
	name = frappe.db.get_value(DOCTYPE, {"company": company}, "name")
	if not name:
		return {
			"company": company,
			"status": "Not Started",
			"version": "new",
			"steps": [],
			**{("profile" if k == "company" else k): config(company, k) for k in STEPS},
		}
	doc = frappe.get_doc(DOCTYPE, name)
	return {
		"company": company,
		"status": doc.status,
		"version": str(doc.modified),
		"steps": frappe.parse_json(doc.completed_steps_json or "[]"),
		**{("profile" if k == "company" else k): config(company, k) for k in STEPS},
	}


def locked(company, expected):
	frappe.db.get_value("Company", company, "name", for_update=True)
	current = state(company)
	if expected != current["version"]:
		frappe.throw(_("Setup changed. Reload before saving."), frappe.TimestampMismatchError)
	name = frappe.db.get_value(DOCTYPE, {"company": company}, "name")
	return (
		frappe.get_doc(DOCTYPE, name)
		if name
		else frappe.get_doc(
			{"doctype": DOCTYPE, "company": company, "status": "In Progress", "completed_steps_json": "[]"}
		)
	)


def save_step(doc, step, values):
	doc.set(step + "_json", json.dumps(values))
	doc.completed_steps_json = json.dumps(
		sorted(set(frappe.parse_json(doc.completed_steps_json or "[]")) | {step})
	)
	doc.status = "In Progress"
	doc.save(ignore_permissions=True)
	return state(doc.company)


def fields(values, allowed):
	values = frappe.parse_json(values)
	if not isinstance(values, dict) or set(values) - set(allowed):
		frappe.throw(_("Unsupported setup fields"))
	return values


def text(value, label, maximum=140):
	if not isinstance(value, str) or not value.strip() or len(value) > maximum:
		frappe.throw(_("Enter a valid {0}").format(label))
	return value.strip()


def number(value, label, minimum=0, maximum=1000000):
	try:
		value = Decimal(str(value))
	except (InvalidOperation, ValueError):
		frappe.throw(_("Enter a valid {0}").format(label))
	if not value.is_finite() or not minimum <= value <= maximum:
		frappe.throw(_("{0} is outside the allowed range").format(label))
	return float(value)


def save_company(ctx, payload, expected):
	values = fields(payload, {"locations", "days", "opens", "closes"})
	doc = locked(ctx.company, expected)
	locations, days = values.get("locations"), values.get("days")
	if not isinstance(locations, list) or not 1 <= len(locations) <= 20:
		frappe.throw(_("Enter one to twenty business locations"))
	if (
		not isinstance(days, list)
		or not days
		or any((not isinstance(x, int) or isinstance(x, bool)) or x not in range(7) for x in days)
	):
		frappe.throw(_("Choose business days from Monday through Sunday"))
	try:
		opens, closes = time.fromisoformat(values["opens"]), time.fromisoformat(values["closes"])
	except (ValueError, KeyError, TypeError):
		frappe.throw(_("Enter valid opening and closing times"))
	if opens >= closes:
		frappe.throw(_("Closing time must be after opening time"))
	old = {row["address"] for row in config(ctx.company, "company").get("locations", [])}
	result = []
	for raw in locations:
		row = fields(raw, {"name", "address_line1", "city", "country", "address"})
		for key in ("name", "address_line1", "city", "country"):
			row[key] = text(row.get(key), key)
		if not frappe.db.exists("Country", row["country"]):
			frappe.throw(_("Choose an existing country"))
		if row.get("address"):
			if row["address"] not in old:
				frappe.throw(_("Location is outside this company's setup"), frappe.PermissionError)
			address = frappe.get_doc("Address", row["address"])
			if not any(
				link.link_doctype == "Company" and link.link_name == ctx.company for link in address.links
			):
				frappe.throw(_("Location no longer belongs to this company"), frappe.PermissionError)
		else:
			address = frappe.get_doc(
				{
					"doctype": "Address",
					"address_type": "Office",
					"links": [{"link_doctype": "Company", "link_name": ctx.company}],
				}
			)
		address.update(
			{
				"address_title": f"{ctx.company}: {row['name']}",
				**{k: row[k] for k in ("address_line1", "city", "country")},
			}
		)
		address.save(ignore_permissions=True)
		result.append({**row, "address": address.name})
	price_list = f"Field OS {ctx.company}"
	currency = frappe.db.get_value("Company", ctx.company, "default_currency")
	if not frappe.db.exists("Price List", price_list):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": price_list,
				"currency": currency,
				"selling": 1,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	elif not frappe.db.exists(
		"Price List", {"name": price_list, "currency": currency, "enabled": 1, "selling": 1}
	):
		frappe.throw(_("The company selling price list has incompatible settings"))
	return save_step(
		doc,
		"company",
		{
			"locations": result,
			"days": sorted(set(days)),
			"opens": opens.isoformat(),
			"closes": closes.isoformat(),
			"price_list": price_list,
		},
	)


def skills(value):
	if not isinstance(value, list) or len(value) > 30:
		frappe.throw(_("Choose up to thirty technician skills"))
	return sorted({text(x, "skill", 60) for x in value})


def save_user(ctx, payload, expected):
	row = fields(
		payload,
		{"email", "first_name", "role", "password", "skills", "gender", "date_of_birth", "date_of_joining"},
	)
	doc = locked(ctx.company, expected)
	email = text(row.get("email"), "email").lower()
	if validate_email_address(email, throw=False) != email:
		frappe.throw(_("Enter one valid user email address"))
	role = row.get("role")
	if role not in {r.value for r in FieldOSRole}:
		frappe.throw(_("Choose a Field OS role"))
	first_name = text(row.get("first_name"), "name")
	known = {u["email"]: u for u in config(ctx.company, "users")}
	exists = frappe.db.exists("User", email)
	if exists:
		if _allowed_companies(email) != {ctx.company} or "System Manager" in frappe.get_roles(email):
			frappe.throw(
				_("Only accounts belonging exclusively to this company can be managed here"),
				frappe.PermissionError,
			)
		if email not in known:
			frappe.throw(
				_("Manage existing accounts through the system administrator"), frappe.PermissionError
			)
		if email == ctx.user and role != "Field OS Owner":
			frappe.throw(_("Keep your owner access while configuring the company"))
		if known[email].get("technician") and role != "Field OS Technician":
			frappe.throw(_("Keep the technician role while an active dispatch profile exists"))
		user = frappe.get_doc("User", email)
		# Global native roles must not let a tenant owner retain or elevate unrelated privileges.
		if any(
			r.role not in {r.value for r in FieldOSRole} | {"All", "Guest", "Desk User", "Employee"}
			for r in user.roles
		):
			frappe.throw(_("This account has additional roles; ask a system administrator to change it"))
	else:
		if not isinstance(row.get("password"), str) or len(row["password"]) < 12:
			frappe.throw(_("Set an initial password of at least twelve characters"))
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"user_type": "System User",
				"send_welcome_email": 0,
				"new_password": row["password"],
			}
		)
	user.first_name = first_name
	user.set(
		"roles",
		[{"role": role}]
		+ (
			[{"role": "Employee"}]
			if exists and frappe.db.exists("Employee", {"user_id": email, "company": ctx.company})
			else []
		),
	)
	user.save(ignore_permissions=True)
	if not exists:
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": email,
				"allow": "Company",
				"for_value": ctx.company,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		frappe.defaults.set_user_default("company", ctx.company, email)
	member = {"email": email, "first_name": first_name, "role": role, "skills": skills(row.get("skills", []))}
	if role == "Field OS Technician":
		employee_name = frappe.db.get_value("Employee", {"user_id": email, "company": ctx.company}, "name")
		if employee_name:
			employee = frappe.get_doc("Employee", employee_name)
		else:
			if row.get("gender") in {
				"Female",
				"Male",
				"Non-binary",
				"Prefer not to say",
			} and not frappe.db.exists("Gender", row["gender"]):
				frappe.get_doc({"doctype": "Gender", "gender": row["gender"]}).insert(ignore_permissions=True)
			if (
				not row.get("date_of_birth")
				or not row.get("date_of_joining")
				or not frappe.db.exists("Gender", row.get("gender"))
			):
				frappe.throw(
					_(
						"Technicians require gender, date of birth and joining date for their native employee record"
					)
				)
			if getdate(row["date_of_birth"]) >= getdate() or getdate(row["date_of_joining"]) > getdate():
				frappe.throw(_("Check the technician's birth and joining dates"))
			employee = frappe.get_doc(
				{
					"doctype": "Employee",
					"company": ctx.company,
					"user_id": email,
					"first_name": first_name,
					"status": "Active",
					"gender": row["gender"],
					"date_of_birth": row["date_of_birth"],
					"date_of_joining": row["date_of_joining"],
					"create_user_permission": 0,
				}
			).insert(ignore_permissions=True)
		person = frappe.db.get_value("Sales Person", {"employee": employee.name}, "name")
		if not person:
			person = (
				frappe.get_doc(
					{
						"doctype": "Sales Person",
						"sales_person_name": f"{ctx.company}: {email}",
						"employee": employee.name,
						"enabled": 1,
						"is_group": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		member["technician"] = person
	elif exists and known[email].get("technician"):
		frappe.throw(_("Keep the technician role while an active dispatch profile exists"))
	known[email] = member
	return save_step(doc, "users", list(known.values()))


def save_services(ctx, payload, expected):
	rows = frappe.parse_json(payload)
	if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
		frappe.throw(_("Configure between one and fifty service types"))
	doc = locked(ctx.company, expected)
	previous = {r["item"] for r in config(ctx.company, "services")}
	result = []
	for raw in rows:
		row = fields(raw, {"name", "rate", "skill", "item"})
		name, skill = text(row.get("name"), "service name", 80), text(row.get("skill"), "required skill", 60)
		rate = number(row.get("rate"), "service rate")
		if row.get("item"):
			if row["item"] not in previous:
				frappe.throw(_("Service item is outside this setup"), frappe.PermissionError)
			item = frappe.get_doc("Item", row["item"])
			if not item.restrict_to_companies or {r.company for r in item.allowed_companies} != {ctx.company}:
				frappe.throw(_("Service item must belong exclusively to this company"))
		else:
			code = f"{ctx.company}: {name}"
			if frappe.db.exists("Item", code):
				frappe.throw(_("A service with this name already exists; edit it instead"))
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"stock_uom": "Nos",
					"item_group": "Services",
					"is_stock_item": 0,
					"is_sales_item": 1,
					"restrict_to_companies": 1,
					"allowed_companies": [{"company": ctx.company}],
				}
			)
		item.update({"item_name": name, "description": name})
		# Create the price explicitly in this company's selling list. Native Item's
		# first-insert price hook uses a global default and requires broader permissions.
		if not row.get("item"):
			item.standard_rate = 0
			item.insert(ignore_permissions=True)
		item.standard_rate = rate
		item.save(ignore_permissions=True)
		company_price_list = price_list(ctx.company)
		if not company_price_list:
			frappe.throw(_("Save company locations and hours before service types"))
		existing_price = frappe.db.get_value(
			"Item Price", {"item_code": item.name, "price_list": company_price_list}, "name"
		)
		price = (
			frappe.get_doc("Item Price", existing_price)
			if existing_price
			else frappe.get_doc(
				{"doctype": "Item Price", "item_code": item.name, "price_list": company_price_list}
			)
		)
		price.price_list_rate = rate
		price.save(ignore_permissions=True)
		result.append({"name": name, "rate": rate, "skill": skill, "item": item.name})
	return save_step(doc, "services", result)


def save_notifications(ctx, payload, expected):
	row = fields(payload, {"preferred_channel", "email_integration", "sms_integration", "invoice_due_days"})
	if row.get("preferred_channel") not in {"None", "Email", "SMS"}:
		frappe.throw(_("Choose a preferred notification channel"))
	for kind in ("email", "sms"):
		if row.get(kind + "_integration") and not frappe.db.exists(
			f"Field OS {kind.upper() if kind == 'sms' else 'Email'} Integration",
			{"name": row[kind + "_integration"], "company": ctx.company, "enabled": 1},
		):
			frappe.throw(_("Choose an enabled integration in this company"), frappe.PermissionError)
	row["invoice_due_days"] = int(number(row.get("invoice_due_days", 30), "invoice due days", maximum=90))
	return save_step(locked(ctx.company, expected), "notifications", row)


def checks(company):
	data, notifications = state(company), config(company, "notifications")
	company_doc = frappe.get_doc("Company", company)
	checks = [
		{"key": step, "label": step.title() + " saved", "ok": step in data["steps"], "required": True}
		for step in STEPS
	]
	checks.append(
		{
			"key": "accounting",
			"label": "Native receivable, income and cost accounts configured",
			"ok": all(
				company_doc.get(k)
				for k in (
					"default_receivable_account",
					"default_income_account",
					"default_expense_account",
					"cost_center",
				)
			),
			"required": True,
		}
	)
	from erpnext.field_os.dispatch.frappe_repository import FrappeDispatchRepository

	technicians = FrappeDispatchRepository().list_technicians(company)
	checks.append(
		{
			"key": "technicians",
			"label": "Active dispatch technician",
			"ok": bool(technicians),
			"required": True,
		}
	)
	configured_skills = {
		skill
		for member in data["users"]
		if member["role"] == "Field OS Technician"
		for skill in member["skills"]
	}
	checks.append(
		{
			"key": "skills",
			"label": "Every service has a qualified technician",
			"ok": bool(data["services"]) and all(s["skill"] in configured_skills for s in data["services"]),
			"required": True,
		}
	)
	for kind in ("Email", "SMS"):
		name = notifications.get(kind.lower() + "_integration")
		integration = (
			frappe.db.get_value(
				f"Field OS {kind} Integration",
				{"name": name, "company": company, "enabled": 1},
				["name", "from_address" if kind == "Email" else "from_number"],
				as_dict=True,
			)
			if name
			else None
		)
		ok = bool(integration)
		if kind == "Email" and integration:
			ok = bool(
				frappe.db.exists(
					"Email Account", {"email_id": integration.from_address, "enable_outgoing": 1}
				)
			)
		if kind == "SMS" and integration:
			ok = bool(frappe.db.get_single_value("SMS Settings", "sms_gateway_url"))
		checks.append(
			{
				"key": kind.lower(),
				"label": kind + " sending configuration",
				"ok": ok,
				"required": notifications.get("preferred_channel") == kind,
			}
		)
	return checks


def complete(ctx, expected):
	doc = locked(ctx.company, expected)
	failed = [row["label"] for row in checks(ctx.company) if row["required"] and not row["ok"]]
	if failed:
		frappe.throw(_("Finish setup first: {0}").format(", ".join(failed)))
	doc.status = "Completed"
	doc.save(ignore_permissions=True)
	return state(ctx.company)


def check_schedule(company, technician, start, end, items=()):
	"""Use saved hours and service qualifications in every Field OS scheduling path."""
	if frappe.db.get_value(DOCTYPE, {"company": company}, "status") != "Completed":
		return
	company_settings = config(company, "company")
	if (
		start.date() != end.date()
		or start.weekday() not in company_settings["days"]
		or start.time().replace(tzinfo=None) < time.fromisoformat(company_settings["opens"])
		or end.time().replace(tzinfo=None) > time.fromisoformat(company_settings["closes"])
	):
		frappe.throw(_("Schedule this visit within the company's business hours"))
	required = {row["skill"] for row in config(company, "services") if row["item"] in items}
	member_skills = {
		skill
		for row in config(company, "users")
		if row.get("technician") == technician
		for skill in row["skills"]
	}
	if not required.issubset(member_skills):
		frappe.throw(_("Choose a technician qualified for this service type"))


def price_list(company):
	return config(company, "company").get("price_list")
