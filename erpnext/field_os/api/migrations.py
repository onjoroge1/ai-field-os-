"""Owner-only import previews, explicit application and approved rollback."""

import frappe

from erpnext.field_os.commercial.access import entitled
from erpnext.field_os.migrations import native


@frappe.whitelist()
def template(company: str, kind: str):
	native.context(company)
	return native.template(kind)


@frappe.whitelist()
def list_batches(company: str):
	native.context(company)
	return frappe.get_all(
		native.BATCH,
		filters={"company": company},
		fields=["name", "migration_kind", "status", "creation", "owner"],
		order_by="creation desc",
		limit=100,
	)


@frappe.whitelist()
def get_batch(company: str, batch_id: str):
	return native.detail(native.document(native.context(company), batch_id))


@frappe.whitelist(methods=["POST"])
@entitled
def validate_csv(company: str, kind: str, content: str):
	return native.validate(native.context(company), kind, content)


@frappe.whitelist(methods=["POST"])
@entitled
def apply(company: str, batch_id: str, version: str):
	return native.apply(native.context(company), batch_id, version)


@frappe.whitelist(methods=["POST"])
@entitled
def preview_rollback(company: str, batch_id: str):
	return native.preview_rollback(native.context(company), batch_id)


@frappe.whitelist(methods=["POST"])
@entitled
def approve_rollback(company: str, proposal_id: str, idempotency_key: str):
	return native.rollback(native.context(company), proposal_id, idempotency_key)
