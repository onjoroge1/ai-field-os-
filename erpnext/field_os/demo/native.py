"""Real synthetic HVAC sandboxes; reset switches to a fresh, isolated generation."""

import csv
import hashlib
import io
import json
from dataclasses import asdict
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, nowdate

from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.agreements.service import add_months
from erpnext.field_os.api import agreements, estimates, onboarding
from erpnext.field_os.completions.billing import load_proposal, proposal, retry_key
from erpnext.field_os.demo.service import SCENARIOS
from erpnext.field_os.migrations import native as migration
from erpnext.field_os.onboarding import native as setup
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context

DOCTYPE = "Field OS Demo Tenant"


def manager():
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("A system administrator must create or reset demo companies"), frappe.PermissionError)


def registered(company):
	return frappe.db.get_value(DOCTYPE, {"company": company}, "name")


def status(company):
	ctx = resolve_tenant_context(company)
	authorize(ctx, "read")
	name = registered(company)
	result = {"company": company, "system_manager": ctx.system_manager, "demo": bool(name)}
	if not name:
		return result
	doc = frappe.get_doc(DOCTYPE, name)
	manifest = frappe.parse_json(doc.manifest_json)
	result.update(
		status=doc.status,
		label=doc.label,
		generation=doc.generation,
		version=str(doc.modified),
		replacement=doc.replacement_company,
		manifest=manifest,
		scenarios=[asdict(s) for s in SCENARIOS],
	)
	return result


def csv_batch(ctx, kind, rows):
	out = io.StringIO()
	writer = csv.writer(out)
	writer.writerow(migration.SCHEMAS[kind][0])
	writer.writerows(rows)
	batch = migration.validate(ctx, kind, out.getvalue())
	batch = migration.apply(ctx, batch["name"], batch["version"])
	if batch["status"] != "Applied":
		frappe.throw(_("Synthetic data could not be imported; no demo was created"))
	return batch["name"]


def create(label, password, key_value, generation=1):
	manager()
	label = setup.text(label, "demo company name", 50)
	if not isinstance(password, str) or len(password) < 12:
		frappe.throw(_("Set a demo login password of at least twelve characters"))
	ctx = resolve_tenant_context(
		frappe.defaults.get_user_default("company") or frappe.get_all("Company", pluck="name", limit=1)[0]
	)
	if not key_value or len(key_value) > 140:
		frappe.throw(_("A creation key of at most 140 characters is required"))
	digest = hashlib.sha256(f"{ctx.user}\0create_demo\0{key_value}".encode()).hexdigest()
	# Serialize retries for the same administrator, including the first request.
	frappe.db.get_value("User", ctx.user, "name", for_update=True)
	existing = frappe.db.get_value(DOCTYPE, {"creation_key": digest}, ["company", "label"], as_dict=True)
	if existing:
		if existing.label != label:
			frappe.throw(_("This creation key belongs to another demo"))
		return status(existing.company)
	token = uuid4().hex[:10]
	company = onboarding.create_company(f"{label} Demo {token}", "D" + token[:4], "United States", "USD")[
		"company"
	]
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"company": company,
			"label": label,
			"generation": generation,
			"seed_version": "hvac-v1",
			"status": "Seeding",
			"creation_key": digest,
			"manifest_json": "{}",
		}
	).insert(ignore_permissions=True)
	seed(doc, password, token)
	doc.status, doc.seeded_at = "Ready", now_datetime()
	doc.save(ignore_permissions=True)
	return status(company)


def seed(doc, password, token):
	company = doc.company
	ctx = setup.context(company)
	state = setup.save_company(
		ctx,
		{
			"locations": [
				{
					"name": "Service center",
					"address_line1": "100 Example Avenue",
					"city": "Boston",
					"country": "United States",
				}
			],
			"days": list(range(7)),
			"opens": "07:00",
			"closes": "19:00",
		},
		"new",
	)
	users = []
	for prefix, name, role in (
		("owner", "Morgan Demo Owner", "Field OS Owner"),
		("tech", "Avery Demo Technician", "Field OS Technician"),
	):
		member = {
			"email": f"{prefix}-{token}@example.invalid",
			"first_name": name,
			"role": role,
			"password": password,
			"skills": ["Heating", "Cooling"],
			"gender": "Prefer not to say",
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2020-01-01",
		}
		state = setup.save_user(ctx, member, state["version"])
		users.append({"email": member["email"], "role": role})
	state = setup.save_services(
		ctx,
		[
			{"name": "Cooling diagnostic", "rate": 125, "skill": "Cooling"},
			{"name": "Heating tune-up", "rate": 149, "skill": "Heating"},
		],
		state["version"],
	)
	state = setup.save_notifications(
		ctx, {"preferred_channel": "None", "invoice_due_days": 14}, state["version"]
	)
	setup.complete(ctx, state["version"])
	service = state["services"][0]["item"]
	technician = next(u["technician"] for u in state["users"] if u.get("technician"))
	batches = [
		csv_batch(
			ctx,
			"customers",
			[
				["cafe", f"Harbor Cafe {token}", f"cafe-{token}@example.invalid", ""],
				["home", f"Taylor Residence {token}", f"taylor-{token}@example.invalid", ""],
				["clinic", f"Pine Clinic {token}", f"clinic-{token}@example.invalid", ""],
			],
		)
	]
	batches.append(
		csv_batch(
			ctx,
			"sites",
			[
				[
					"cafe-site",
					"cafe",
					"Harbor Cafe rooftop",
					"10 Example Harbor Lane",
					"Boston",
					"MA",
					"02110",
				],
				["home-site", "home", "Taylor basement", "20 Example Oak Street", "Boston", "MA", "02111"],
				[
					"clinic-site",
					"clinic",
					"Pine Clinic plant room",
					"30 Example Pine Avenue",
					"Boston",
					"MA",
					"02112",
				],
			],
		)
	)
	batches.append(
		csv_batch(
			ctx,
			"equipment",
			[
				[
					"cafe-rtu",
					"cafe",
					"cafe-site",
					"Cafe rooftop cooling unit",
					"Packaged rooftop",
					"DEMO-RTU-5",
					"SYNTH-001",
					"2019-05-10",
				],
				[
					"home-heat",
					"home",
					"home-site",
					"Taylor heat pump",
					"Heat pump",
					"DEMO-HP-3",
					"SYNTH-002",
					"2022-10-05",
				],
				[
					"clinic-boiler",
					"clinic",
					"clinic-site",
					"Clinic condensing boiler",
					"Boiler",
					"DEMO-CB-80",
					"SYNTH-003",
					"2020-02-20",
				],
			],
		)
	)
	customers = {
		key: migration.mapping(company, "customers", key).target_name for key in ("cafe", "home", "clinic")
	}
	sites = {key: migration.mapping(company, "sites", key + "-site").target_name for key in customers}
	unit = migration.mapping(company, "equipment", "cafe-rtu").target_name
	frappe.get_doc(
		{
			"doctype": "Field OS Equipment Note",
			"company": company,
			"customer": customers["cafe"],
			"site": sites["cafe"],
			"equipment": unit,
			"note": "Synthetic service history: cleaned condenser coil and replaced belt. Watch intermittent cooling on hot afternoons.",
			"technician": users[1]["email"],
			"occurred_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	agreement = agreements.save_agreement(
		company,
		customers["clinic"],
		sites["clinic"],
		{
			"starts_on": add_months(getdate(), -11).isoformat(),
			"ends_on": add_days(nowdate(), 20),
			"interval_months": 3,
			"renewal_notice_days": 30,
			"service_item": service,
		},
	)
	agreement = agreements.set_status(company, agreement["name"], "Active", agreement["modified"])
	job = frappe.get_doc(
		{
			"doctype": "Maintenance Visit",
			"company": company,
			"customer": customers["cafe"],
			"customer_address": sites["cafe"],
			"mntc_date": nowdate(),
			"mntc_time": "10:00:00",
			"maintenance_type": "Unscheduled",
			"completion_status": "Partially Completed",
			"purposes": [
				{
					"item_code": service,
					"service_person": technician,
					"description": "Synthetic urgent no-cooling diagnostic",
					"work_done": "Planned demo diagnostic; work has not been performed",
				}
			],
		}
	).insert(ignore_permissions=True)
	thread = frappe.get_doc(
		{
			"doctype": "Field OS Communication Thread",
			"company": company,
			"subject": "DEMO: Cafe dining room has no cooling",
			"channel": "email",
			"status": "open",
			"classification": "service_request",
			"customer": customers["cafe"],
			"site": sites["cafe"],
			"job": job.name,
			"last_message_at": now_datetime(),
			"sla_due_at": now_datetime(),
			"participants": [
				{
					"address": f"cafe-{token}@example.invalid",
					"participant_role": "customer",
					"display_name": "Jordan at Harbor Cafe",
				}
			],
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Field OS Communication Message",
			"company": company,
			"thread": thread.name,
			"channel": "email",
			"direction": "inbound",
			"delivery_status": "received",
			"occurred_at": now_datetime(),
			"sender_address": f"cafe-{token}@example.invalid",
			"sender_name": "Jordan at Harbor Cafe",
			"sender_role": "customer",
			"recipients_json": "[]",
			"subject": thread.subject,
			"body": "Synthetic demo request: our dining room is 84 degrees and lunch service starts at noon. The rooftop unit runs but only blows warm air. Please send a technician this morning.",
			"classification": "service_request",
			"provider": "synthetic-demo",
		}
	).insert(ignore_permissions=True)
	mailbox = frappe.get_doc(
		{
			"doctype": "Field OS Email Integration",
			"company": company,
			"enabled": 1,
			"provider": "Demo (delivery blocked)",
			"mailbox_key": "demo-" + token,
			"from_address": f"dispatch-{token}@example.invalid",
			"webhook_secret": uuid4().hex,
			"poll_enabled": 0,
		}
	).insert(ignore_permissions=True)
	estimate = estimates.save_estimate(
		company,
		customers["cafe"],
		{
			"recipient": f"cafe-{token}@example.invalid",
			"email_integration": mailbox.name,
			"valid_until": add_days(nowdate(), 30),
			"items": [{"item_code": service, "qty": 1, "rate": 125}],
		},
	)
	quote = frappe.get_doc("Quotation", estimate["quotation"])
	quote.flags.ignore_permissions = True
	quote.submit()
	approved = frappe.get_doc("Field OS Estimate", estimate["name"])
	approved.status = "Approved"
	approved.save(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Field OS Estimate Decision",
			"company": company,
			"estimate": quote.name,
			"field_os_estimate": approved.name,
			"decision": "Approved",
			"customer_name": "Jordan (synthetic customer)",
			"decided_at": now_datetime(),
			"recorded_by": frappe.session.user,
			"evidence": "Synthetic approval seeded for demo practice; no customer communication occurred.",
			"comment": "Demo authorization for cooling diagnostic",
		}
	).insert(ignore_permissions=True)
	doc.manifest_json = json.dumps(
		{
			"customers": customers,
			"sites": sites,
			"equipment": unit,
			"agreement": agreement["name"],
			"job": job.name,
			"thread": thread.name,
			"estimate": approved.name,
			"users": users,
			"batches": batches,
			"service": service,
		}
	)


def preview_reset(company):
	manager()
	ctx = resolve_tenant_context(company)
	name = registered(company)
	if not name:
		frappe.throw(_("Only a registered demo company can be reset"))
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status != "Ready":
		frappe.throw(_("Open the current demo generation before resetting"))
	item = proposal(
		ctx, "reset_native_demo", {"demo": name, "version": str(doc.modified)}, RiskClass.DESTRUCTIVE
	)
	return {
		"proposal": asdict(item),
		"company": company,
		"next_generation": doc.generation + 1,
		"effect": "Create a fresh synthetic company, archive this generation and disable its demo logins. Existing records and posted invoices remain in the archived company.",
	}


def reset(company, proposal_id, key_value, password):
	manager()
	ctx = resolve_tenant_context(company)
	name = registered(company)
	if not name:
		frappe.throw(_("Only a registered demo company can be reset"))
	frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
	doc = frappe.get_doc(DOCTYPE, name)
	digest = retry_key(ctx, "reset_native_demo", key_value)
	if doc.reset_key == digest and doc.reset_proposal == proposal_id:
		return status(doc.replacement_company)
	item = load_proposal(ctx, proposal_id, "reset_native_demo", RiskClass.DESTRUCTIVE)
	if item.arguments != {"demo": name, "version": str(doc.modified)} or doc.status != "Ready":
		frappe.throw(_("Demo changed. Review a fresh reset preview."))
	result = create(doc.label, password, "reset-" + digest, doc.generation + 1)
	for user in frappe.parse_json(doc.manifest_json)["users"]:
		account = frappe.get_doc("User", user["email"])
		# Disable only the exact synthetic accounts, still restricted to this tenant.
		if setup._allowed_companies(account.name) != {company} or "System Manager" in frappe.get_roles(
			account.name
		):
			frappe.throw(_("Demo account ownership changed; reset requires administrator review"))
		account.enabled = 0
		account.save(ignore_permissions=True)
	doc.update(
		{
			"status": "Archived",
			"replacement_company": result["company"],
			"reset_key": digest,
			"reset_proposal": proposal_id,
			"reset_by": ctx.user,
			"reset_at": now_datetime(),
		}
	)
	doc.save(ignore_permissions=True)
	return result
