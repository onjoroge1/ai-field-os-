"""Reviewed, atomic imports of native customer, address and equipment records."""

import csv
import hashlib
import io
import json
from dataclasses import asdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import now_datetime, validate_email_address

from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.completions.billing import load_proposal, proposal, retry_key
from erpnext.field_os.migrations.service import SCHEMAS
from erpnext.field_os.onboarding.native import context

BATCH = "Field OS Migration Batch"
RECORD = "Field OS Migration Record"
TARGETS = {"customers": "Customer", "sites": "Address", "equipment": "Field OS HVAC Equipment"}


def key(company, kind, external_id):
	return hashlib.sha256(f"{company}\0{kind}\0{external_id}".encode()).hexdigest()


def mapping(company, kind, external_id):
	return frappe.db.get_value(
		RECORD,
		{"key_hash": key(company, kind, external_id)},
		["name", "target_name", "customer"],
		as_dict=True,
	)


def document(ctx, name, lock=False):
	if lock:
		frappe.db.get_value("Company", ctx.company, "name", for_update=True)
	if not frappe.db.exists(BATCH, {"name": name, "company": ctx.company}):
		frappe.throw(_("Import is not available in this company"), frappe.PermissionError)
	return frappe.get_doc(BATCH, name)


def detail(doc):
	return {
		"name": doc.name,
		"company": doc.company,
		"kind": doc.migration_kind,
		"status": doc.status,
		"version": str(doc.modified),
		"created_by": doc.owner,
		"creation": doc.creation,
		"applied_by": doc.applied_by,
		"rolled_back_by": doc.rolled_back_by,
		"rows": frappe.parse_json(doc.rows_json),
		"records": frappe.parse_json(doc.created_records_json or "[]"),
		"error_report": doc.error_report or "",
	}


def template(kind):
	if kind not in SCHEMAS:
		frappe.throw(_("Choose customers, sites or equipment"))
	out = io.StringIO()
	csv.writer(out).writerow(SCHEMAS[kind][0])
	return out.getvalue()


def parse(kind, content):
	template(kind)
	if not isinstance(content, str) or len(content.encode()) > 2_000_000:
		frappe.throw(_("CSV must be smaller than 2 MB"))
	fields, required = SCHEMAS[kind]
	reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
	try:
		columns = reader.fieldnames or []
		if len(columns) != len(set(columns)) or set(columns) - set(fields) or set(required) - set(columns):
			frappe.throw(_("CSV columns must match the downloaded template"))
		rows, seen = [], set()
		for number, raw in enumerate(reader, 2):
			if number > 1001:
				frappe.throw(_("Import at most 1000 rows at a time"))
			data = {field: (raw.get(field) or "").strip() for field in fields}
			errors = [f"{field} is required" for field in required if not data[field]]
			if None in raw or any(v is None for v in raw.values()):
				errors.append("Row width does not match the header")
			if any(len(v) > 140 or any(ord(c) < 32 for c in v) for v in data.values()):
				errors.append("Cells must be at most 140 characters without control characters")
			external_id = data[fields[0]]
			if external_id in seen:
				errors.append("Duplicate external identifier in this file")
			seen.add(external_id)
			if (
				kind == "customers"
				and data["email"]
				and validate_email_address(data["email"], throw=False) != data["email"]
			):
				errors.append("Enter one valid email address")
			if kind == "sites" and not data["city"]:
				errors.append("city is required")
			if kind == "equipment" and data["installed_on"]:
				try:
					date.fromisoformat(data["installed_on"])
				except ValueError:
					errors.append("installed_on must be an ISO date")
			rows.append({"number": number, "data": data, "errors": errors})
	except csv.Error:
		frappe.throw(_("CSV is malformed; export it again using the template"))
	if not rows:
		frappe.throw(_("CSV must contain data rows"))
	return rows


def validate_references(company, kind, rows):
	for row in rows:
		data, errors = row["data"], row["errors"]
		if mapping(company, kind, data[SCHEMAS[kind][0][0]]):
			errors.append("External identifier was already imported into this company")
		if kind == "customers":
			continue
		customer = mapping(company, "customers", data["customer_id"])
		if not customer or not frappe.db.exists("Customer", customer.target_name):
			errors.append("Import this customer_id into this company first")
			continue
		from erpnext.stock.doctype.company_restriction.company_restriction import validate_masters_for_company

		validate_masters_for_company("Customer", [customer.target_name], company)
		if kind == "equipment":
			site = mapping(company, "sites", data["site_id"])
			if (
				not site
				or site.customer != customer.target_name
				or not frappe.db.exists(
					"Dynamic Link",
					{
						"parenttype": "Address",
						"parent": site.target_name,
						"link_doctype": "Customer",
						"link_name": customer.target_name,
					},
				)
			):
				errors.append("Import this site_id for the same customer first")
	return rows


def safe_cell(value):
	value = str(value)
	return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def error_csv(rows):
	out = io.StringIO()
	writer = csv.writer(out)
	writer.writerow(["row", "external_id", "errors"])
	for row in rows:
		if row["errors"]:
			writer.writerow(
				[
					row["number"],
					safe_cell(next(iter(row["data"].values()))),
					safe_cell("; ".join(row["errors"])),
				]
			)
	return out.getvalue()


def validate(ctx, kind, content):
	rows = validate_references(ctx.company, kind, parse(kind, content))
	doc = frappe.get_doc(
		{
			"doctype": BATCH,
			"company": ctx.company,
			"migration_kind": kind,
			"status": "Failed Validation" if any(r["errors"] for r in rows) else "Validated",
			"rows_json": json.dumps(rows),
			"error_report": error_csv(rows),
			"dry_run": 1,
			"created_records_json": "[]",
		}
	).insert(ignore_permissions=True)
	return detail(doc)


def fingerprint(doc):
	data = {k: v for k, v in doc.as_dict().items() if not k.startswith("_")}
	return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(doc):
	doc.reload()
	return {"doctype": doc.doctype, "name": doc.name, "fingerprint": fingerprint(doc)}


def create_record(ctx, batch, row):
	data, kind = row["data"], batch.migration_kind
	if kind == "customers":
		# Always create a new, company-restricted customer. Never match global names/emails.
		doc = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": data["customer_name"],
				"customer_type": "Company",
				"customer_group": "Commercial",
				"territory": "All Territories",
				"email_id": data["email"],
				"mobile_no": data["phone"],
				"restrict_to_companies": 1,
				"allowed_companies": [{"company": ctx.company}],
			}
		).insert(ignore_permissions=True)
		customer = doc.name
	elif kind == "sites":
		customer = mapping(ctx.company, "customers", data["customer_id"]).target_name
		doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": data["title"],
				"address_type": "Billing",
				"address_line1": data["address_line1"],
				"city": data["city"],
				"state": data["state"],
				"pincode": data["postal_code"],
				"country": frappe.db.get_value("Company", ctx.company, "country"),
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert(ignore_permissions=True)
	else:
		customer = mapping(ctx.company, "customers", data["customer_id"]).target_name
		site = mapping(ctx.company, "sites", data["site_id"]).target_name
		doc = frappe.get_doc(
			{
				"doctype": TARGETS[kind],
				"company": ctx.company,
				"customer": customer,
				"site": site,
				**{
					k: v or None
					for k, v in data.items()
					if k not in {"equipment_id", "customer_id", "site_id"}
				},
			}
		).insert(ignore_permissions=True)
	external_id = data[SCHEMAS[kind][0][0]]
	frappe.get_doc(
		{
			"doctype": RECORD,
			"company": ctx.company,
			"migration_kind": kind,
			"external_id": external_id,
			"key_hash": key(ctx.company, kind, external_id),
			"target_doctype": doc.doctype,
			"target_name": doc.name,
			"customer": customer,
			"batch": batch.name,
		}
	).insert(ignore_permissions=True)
	records = [snapshot(doc)]
	if kind == "customers" and doc.customer_primary_contact:
		records.append(snapshot(frappe.get_doc("Contact", doc.customer_primary_contact)))
	return records


def apply(ctx, name, version):
	doc = document(ctx, name, lock=True)
	if doc.status == "Applied":
		return detail(doc)
	if str(doc.modified) != version or doc.status != "Validated":
		frappe.throw(_("Review a current, valid dry run before applying"))
	rows = validate_references(ctx.company, doc.migration_kind, frappe.parse_json(doc.rows_json))
	if any(r["errors"] for r in rows):
		doc.status, doc.rows_json, doc.error_report = "Failed Validation", json.dumps(rows), error_csv(rows)
		doc.save(ignore_permissions=True)
		return detail(doc)
	frappe.db.savepoint("fieldos_import")
	try:
		created = []
		for row in rows:
			created.extend(create_record(ctx, doc, row))
	except Exception:
		frappe.db.rollback(save_point="fieldos_import")
		# Retain a safe audit without reflecting database errors or another tenant's data.
		doc.status = "Apply Failed"
		row["errors"].append(
			"Native record validation failed. No records were created; correct this row and run a new dry run."
		)
		doc.rows_json = json.dumps(rows)
		doc.error_report = error_csv(rows)
		doc.save(ignore_permissions=True)
		return detail(doc)
	doc.update(
		{
			"status": "Applied",
			"dry_run": 0,
			"created_records_json": json.dumps(created),
			"applied_by": ctx.user,
			"applied_at": now_datetime(),
		}
	)
	doc.save(ignore_permissions=True)
	return detail(doc)


def rollback_records(doc, lock=False):
	records = frappe.parse_json(doc.created_records_json)
	owned = {(r["doctype"], r["name"]) for r in records}
	for row in records:
		if lock:
			frappe.db.get_value(row["doctype"], row["name"], "name", for_update=True)
		if not frappe.db.exists(row["doctype"], row["name"]):
			frappe.throw(_("An imported record was deleted. Rollback requires administrator review."))
		current = frappe.get_doc(row["doctype"], row["name"])
		if fingerprint(current) != row["fingerprint"]:
			frappe.throw(
				_("An imported record changed. Preserve it and ask an administrator to review the import.")
			)
		if frappe.db.exists(
			"File", {"attached_to_doctype": row["doctype"], "attached_to_name": row["name"]}
		) or frappe.db.exists(
			"Comment",
			{"reference_doctype": row["doctype"], "reference_name": row["name"], "comment_type": "Comment"},
		):
			frappe.throw(_("Imported records have new attachments or comments and cannot be rolled back"))
		if row["doctype"] == "Customer":
			links = frappe.get_all(
				"Dynamic Link",
				filters={"link_doctype": "Customer", "link_name": row["name"]},
				fields=["parenttype", "parent"],
			)
			if any((r.parenttype, r.parent) not in owned for r in links):
				frappe.throw(
					_(
						"This customer has additional addresses or contacts. Roll back dependent imports first."
					)
				)
	return records


def preview_rollback(ctx, name):
	doc = document(ctx, name)
	if doc.status != "Applied":
		frappe.throw(_("Only applied imports can be rolled back"))
	records = rollback_records(doc)
	item = proposal(
		ctx, "rollback_native_migration", {"batch": name, "version": str(doc.modified)}, RiskClass.DESTRUCTIVE
	)
	return {"proposal": asdict(item), "records": records}


def rollback(ctx, proposal_id, key_value):
	digest = retry_key(ctx, "rollback_native_migration", key_value)
	frappe.db.get_value("Company", ctx.company, "name", for_update=True)
	previous = frappe.db.get_value(BATCH, {"company": ctx.company, "rollback_key_hash": digest}, "name")
	if previous:
		doc = document(ctx, previous)
		if doc.rollback_proposal != proposal_id:
			frappe.throw(_("This retry key belongs to another approval"))
		return detail(doc)
	item = load_proposal(ctx, proposal_id, "rollback_native_migration", RiskClass.DESTRUCTIVE)
	doc = document(ctx, item.arguments["batch"])
	if doc.status != "Applied" or str(doc.modified) != item.arguments["version"]:
		frappe.throw(_("Import changed. Review a new rollback preview."))
	records = rollback_records(doc, lock=True)
	frappe.db.savepoint("fieldos_rollback")
	try:
		for name in frappe.get_all(RECORD, filters={"company": ctx.company, "batch": doc.name}, pluck="name"):
			frappe.delete_doc(RECORD, name, ignore_permissions=True)
		# Customer's native on_trash removes its unchanged primary contact.
		for row in records:
			if frappe.db.exists(row["doctype"], row["name"]):
				frappe.delete_doc(row["doctype"], row["name"], ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point="fieldos_rollback")
		frappe.throw(
			_(
				"Rollback was blocked by records linked to this import. No records were removed. Roll back dependent imports first."
			)
		)
	doc.update(
		{
			"status": "Rolled Back",
			"rolled_back_by": ctx.user,
			"rolled_back_at": now_datetime(),
			"rollback_key_hash": digest,
			"rollback_proposal": proposal_id,
		}
	)
	doc.save(ignore_permissions=True)
	return detail(doc)
