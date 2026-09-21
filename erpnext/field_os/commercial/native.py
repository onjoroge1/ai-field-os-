"""Durable usage ledger. Company-row locks serialize quotas and seat changes."""

import hashlib
import json
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import getdate

from erpnext.field_os.commercial.policy import FEATURES, PLANS, period, require_access, require_quota
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context
from erpnext.field_os.security.roles import FieldOSRole

SUBSCRIPTION = "Field OS Subscription"
USAGE = "Field OS Usage"


def lock_company(company):
	table = frappe.qb.DocType("Company")
	if not frappe.qb.from_(table).select(table.name).where(table.name == company).for_update().run():
		raise frappe.DoesNotExistError(company)


def subscription(company, *, lock=False):
	if lock:
		lock_company(company)
	name = frappe.db.get_value(SUBSCRIPTION, {"company": company}, "name")
	if not name:
		if not lock:
			lock_company(company)
			name = frappe.db.get_value(SUBSCRIPTION, {"company": company}, "name")
		if not name:
			return frappe.get_doc(
				{
					"doctype": SUBSCRIPTION,
					"company": company,
					"plan": "trial",
					"status": "trialing",
					"trial_end": getdate() + timedelta(days=30),
					"disabled_features_json": "[]",
				}
			).insert(ignore_permissions=True)
	return frappe.get_doc(SUBSCRIPTION, name)


def provision_company(doc, method=None):
	# During initial schema installation the DocType may not exist yet.
	if frappe.db.table_exists(SUBSCRIPTION):
		subscription(doc.name)


def migrate_subscriptions():
	for company in frappe.get_all("Company", pluck="name"):
		subscription(company)


def state(doc):
	return {
		"plan": doc.plan,
		"status": doc.status,
		"trial_end": doc.trial_end,
		"grace_end": doc.grace_end,
		"disabled_features": json.loads(doc.disabled_features_json or "[]"),
	}


def require(company, feature=None):
	doc = subscription(company, lock=True)
	return require_access(state(doc), feature, today=getdate())


def usage_name(company, metric, key):
	return hashlib.sha256(json.dumps([company, metric, key], separators=(",", ":")).encode()).hexdigest()


def consume(company, metric, key, *, amount=1):
	if not isinstance(key, str) or not 1 <= len(key) <= 500:
		raise ValueError("A bounded usage idempotency key is required")
	doc = subscription(company, lock=True)
	name = usage_name(company, metric, key)
	old = frappe.db.get_value(USAGE, name, ["quantity", "period"], as_dict=True)
	if old:
		if old.quantity != amount:
			raise ValueError("Usage key has already been used with a different quantity")
		return name
	plan = require_access(state(doc), metric, today=getdate())
	current = period(getdate())
	used = totals(company, current).get(metric, 0)
	require_quota(plan, metric, used, amount)
	frappe.get_doc(
		{
			"doctype": USAGE,
			"usage_key": name,
			"company": company,
			"metric": metric,
			"period": current,
			"quantity": amount,
			"actor": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	return name


def totals(company, current):
	from frappe.query_builder.functions import Sum

	table = frappe.qb.DocType(USAGE)
	rows = (
		frappe.qb.from_(table)
		.select(table.metric, Sum(table.quantity).as_("quantity"))
		.where((table.company == company) & (table.period == current))
		.groupby(table.metric)
		.run(as_dict=True)
	)
	return {row.metric: int(row.quantity) for row in rows}


def members(company):
	permission, user, role = (frappe.qb.DocType(name) for name in ("User Permission", "User", "Has Role"))
	rows = (
		frappe.qb.from_(permission)
		.join(user)
		.on(user.name == permission.user)
		.join(role)
		.on((role.parent == user.name) & (role.parenttype == "User"))
		.select(user.name)
		.distinct()
		.where(
			(permission.allow == "Company")
			& (permission.for_value == company)
			& (user.enabled == 1)
			& role.role.isin([r.value for r in FieldOSRole])
		)
		.run()
	)
	return {row[0] for row in rows}


def seat(company, user):
	plan = require(company)
	if len(members(company) | {user}) > plan.seats:
		frappe.throw(_("Company seat limit reached. Open Plan & usage to review your allowance."))


def validate_membership(doc, method=None):
	if doc.allow == "Company" and frappe.db.table_exists(SUBSCRIPTION):
		if frappe.db.get_value("User", doc.user, "enabled") and set(frappe.get_roles(doc.user)).intersection(
			{r.value for r in FieldOSRole}
		):
			seat(doc.for_value, doc.user)


def validate_user(doc, method=None):
	if not doc.enabled or not frappe.db.table_exists(SUBSCRIPTION):
		return
	if not {r.role for r in doc.roles}.intersection({r.value for r in FieldOSRole}):
		return
	for company in sorted(
		set(
			frappe.get_all(
				"User Permission", filters={"user": doc.name, "allow": "Company"}, pluck="for_value"
			)
		)
	):
		seat(company, doc.name)


def summary(company):
	context = resolve_tenant_context(company)
	authorize(context, "admin")
	doc = subscription(company)
	result = state(doc)
	plan = PLANS[doc.plan]
	current = period(getdate())
	result.update(
		{
			"company": company,
			"period": current,
			"usage": totals(company, current),
			"seats": len(members(company)),
			"limits": {name: getattr(plan, name) for name in ("seats", "ai", "email", "sms")},
			"version": str(doc.modified),
			"features": sorted(plan.features - set(result["disabled_features"])),
		}
	)
	return result


def read_permission(doc, ptype=None, user=None, **kwargs):
	try:
		context = resolve_tenant_context(doc.company, user)
		authorize(context, "admin")
		return ptype in (None, "read", "select")
	except PermissionError:
		return False
