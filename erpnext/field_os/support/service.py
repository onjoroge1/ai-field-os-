import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from erpnext.field_os.commercial import native
from erpnext.field_os.commercial.policy import FEATURES
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context

GRANT = "Field OS Support Grant"
AUDIT = "Field OS Audit Event"
SUPPORT_ROLE = "Field OS Support"


def staff():
	if frappe.session.user == "Guest" or not {SUPPORT_ROLE, "System Manager"}.intersection(
		frappe.get_roles()
	):
		frappe.throw(_("Support staff access is required"), frappe.PermissionError)


def owner(company):
	context = resolve_tenant_context(company)
	authorize(context, "admin")
	return context


def reason_text(reason):
	if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 500:
		frappe.throw(_("Enter a support reason between 10 and 500 characters"))
	return reason.strip()


def audit(company, action, *, reference="", outcome="success", details=None):
	# Caller supplies an allowlisted summary. Never pass requests, secrets or message bodies.
	return frappe.get_doc(
		{
			"doctype": AUDIT,
			"company": company,
			"actor": frappe.session.user,
			"action": action,
			"reference": reference,
			"outcome": outcome,
			"correlation_id": getattr(frappe.local, "field_os_correlation", None),
			"details_json": json.dumps(details or {}, sort_keys=True),
		}
	).insert(ignore_permissions=True)


def grant(company, support_user, reason, minutes):
	owner(company)
	reason = reason_text(reason)
	if isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= 60:
		frappe.throw(_("Support access must last between 5 and 60 minutes"))
	if not frappe.db.get_value("User", support_user, "enabled") or SUPPORT_ROLE not in frappe.get_roles(
		support_user
	):
		frappe.throw(_("Choose an enabled Field OS Support account"))
	doc = frappe.get_doc(
		{
			"doctype": GRANT,
			"company": company,
			"support_user": support_user,
			"approved_by": frappe.session.user,
			"reason": reason,
			"expires_at": now_datetime() + timedelta(minutes=minutes),
		}
	).insert(ignore_permissions=True)
	audit(
		company,
		"support.granted",
		reference=doc.name,
		details={"support_user": support_user, "minutes": minutes},
	)
	return grants(company)


def grants(company):
	owner(company)
	return frappe.get_all(
		GRANT,
		filters={"company": company},
		fields=["name", "support_user", "approved_by", "reason", "expires_at", "revoked"],
		order_by="creation desc",
		limit=50,
	)


def revoke(company, name):
	owner(company)
	native.lock_company(company)
	doc = frappe.get_doc(GRANT, name)
	if doc.company != company:
		frappe.throw(_("Support grant belongs to another company"), frappe.PermissionError)
	if not doc.revoked:
		doc.revoked = 1
		doc.save(ignore_permissions=True)
		audit(company, "support.revoked", reference=name)
	return grants(company)


def lookup(query):
	staff()
	if not isinstance(query, str) or not 2 <= len(query.strip()) <= 100:
		return []
	# Staff can locate tenants, but access to operating data requires an owner grant.
	filters = {"company": ["like", "%" + query.strip().replace("%", "").replace("_", "") + "%"]}
	return frappe.get_all(
		native.SUBSCRIPTION,
		filters=filters,
		fields=["company", "plan", "status"],
		order_by="company asc",
		limit=25,
	)


def my_grants():
	staff()
	return frappe.get_all(
		GRANT,
		filters={"support_user": frappe.session.user, "revoked": 0, "expires_at": [">", now_datetime()]},
		fields=["name", "company", "reason", "expires_at"],
		limit=50,
	)


def inspect(company, grant_id, reason):
	staff()
	reason = reason_text(reason)
	if "System Manager" not in frappe.get_roles():
		doc = frappe.get_doc(GRANT, grant_id)
		if (
			doc.company != company
			or doc.support_user != frappe.session.user
			or doc.revoked
			or get_datetime(doc.expires_at) <= now_datetime()
		):
			frappe.throw(_("Support access has expired or was revoked"), frappe.PermissionError)
		# Removing the approving owner's membership revokes delegated access too.
		owner_context = resolve_tenant_context(company, doc.approved_by)
		authorize(owner_context, "admin")
	result = diagnostics(company)
	audit(company, "support.inspected", reference=grant_id, details={"reason": reason, "mode": "read-only"})
	return result


def diagnostics(company):
	doc = native.subscription(company)
	channels = []
	for doctype, channel in (("Field OS Email Integration", "email"), ("Field OS SMS Integration", "sms")):
		for row in frappe.get_all(
			doctype,
			filters={"company": company},
			fields=["name", "enabled", "poll_enabled", "last_error"],
			limit=50,
		):
			channels.append(
				{
					"id": row.name,
					"channel": channel,
					"enabled": bool(row.enabled),
					"polling": bool(row.poll_enabled),
					"has_error": bool(row.last_error),
				}
			)
	return {
		"company": company,
		"subscription": native.state(doc),
		"version": str(doc.modified),
		"integrations": channels,
		"audit": frappe.get_all(
			AUDIT,
			filters={"company": company},
			fields=["creation", "actor", "action", "outcome", "reference", "correlation_id"],
			order_by="creation desc",
			limit=100,
		),
		"counts": {
			kind: frappe.db.count(doctype, {"company": company})
			for kind, doctype in (
				("equipment", "Field OS HVAC Equipment"),
				("agreements", "Field OS Maintenance Agreement"),
				("inbox_threads", "Field OS Communication Thread"),
			)
		},
	}


def flags(company, disabled, version, reason):
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a system administrator can change feature availability"), frappe.PermissionError)
	reason = reason_text(reason)
	if (
		not isinstance(disabled, list)
		or any(not isinstance(value, str) for value in disabled)
		or not set(disabled) <= FEATURES
	):
		frappe.throw(_("Choose supported Field OS features"))
	doc = native.subscription(company, lock=True)
	if str(doc.modified) != version:
		frappe.throw(_("Plan configuration changed; reload it first"), frappe.TimestampMismatchError)
	previous = json.loads(doc.disabled_features_json or "[]")
	doc.disabled_features_json = json.dumps(sorted(set(disabled)))
	doc.save(ignore_permissions=True)
	audit(
		company,
		"features.changed",
		details={"before": previous, "after": sorted(set(disabled)), "reason": reason},
	)
	return diagnostics(company)


def ensure_role():
	if not frappe.db.exists("Role", SUPPORT_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": SUPPORT_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
