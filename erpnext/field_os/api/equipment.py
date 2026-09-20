"""Authenticated equipment lifecycle, service history and private photo uploads."""

import base64
import binascii
import io
from dataclasses import asdict

import frappe
from frappe import _
from frappe.utils import get_datetime

from erpnext.field_os.equipment.frappe_repository import EQUIPMENT, FrappeEquipmentRepository
from erpnext.field_os.equipment.service import EquipmentService
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import resolve_tenant_context

EDITABLE = {
	"equipment_name",
	"unit_type",
	"manufacturer",
	"model_number",
	"serial_number",
	"installed_on",
	"warranty_expires_on",
	"parent_equipment",
	"status",
}


@frappe.whitelist()
def history(company: str, equipment_id: str):
	context = resolve_tenant_context(company)
	repository = FrappeEquipmentRepository()
	result = asdict(EquipmentService(repository).history(context, equipment_id))
	result["modified"] = str(repository.document(company, equipment_id).modified)
	result["visits"] = frappe.get_all(
		"Maintenance Visit",
		filters={"company": company, "customer": result["equipment"]["customer_id"], "docstatus": ["!=", 2]},
		fields=["name", "mntc_date", "status"],
		order_by="mntc_date desc",
		limit=100,
	)
	return result


@frappe.whitelist(methods=["POST"])
def save_equipment(company: str, customer_id: str, site_id: str, values, equipment_id=None, modified=None):
	context = resolve_tenant_context(company)
	authorize(context, "dispatch")
	values = frappe.parse_json(values)
	if not isinstance(values, dict) or set(values) - EDITABLE:
		frappe.throw(_("Only equipment detail fields may be updated"))
	if equipment_id:
		doc = FrappeEquipmentRepository().document(company, equipment_id)
		if (doc.customer, doc.site) != (customer_id, site_id):
			frappe.throw(_("Equipment cannot be moved to another customer or site"))
		if not modified or get_datetime(modified) != get_datetime(doc.modified):
			frappe.throw(_("Equipment changed. Reload before saving."), frappe.TimestampMismatchError)
	else:
		doc = frappe.get_doc(
			{"doctype": EQUIPMENT, "company": company, "customer": customer_id, "site": site_id}
		)
	doc.update(values)
	doc.save()
	return {"name": doc.name, "modified": str(doc.modified)}


@frappe.whitelist(methods=["POST"])
def add_note(company: str, equipment_id: str, note: str, visit_id=None, photo_urls=None):
	photos = frappe.parse_json(photo_urls) if photo_urls else []
	if not isinstance(photos, list) or any(not isinstance(url, str) for url in photos):
		frappe.throw(_("Photos must be a list of private file URLs"))
	context = resolve_tenant_context(company)
	return asdict(
		EquipmentService(FrappeEquipmentRepository()).add_note(
			context, equipment_id, note, visit_id, tuple(photos)
		)
	)


@frappe.whitelist(methods=["POST"])
def upload_photo(company: str, equipment_id: str, content: str):
	from PIL import Image, UnidentifiedImageError

	context = resolve_tenant_context(company)
	authorize(context, "field_update")
	FrappeEquipmentRepository().document(company, equipment_id)
	if not isinstance(content, str) or len(content) > 7_000_000:
		frappe.throw(_("Photo must be smaller than 5 MB"))
	try:
		data = base64.b64decode(content, validate=True)
		if len(data) > 5_000_000:
			frappe.throw(_("Photo must be smaller than 5 MB"))
		with Image.open(io.BytesIO(data)) as picture:
			if picture.format not in {"JPEG", "PNG", "WEBP"} or picture.width * picture.height > 25_000_000:
				frappe.throw(_("Use a JPEG, PNG or WebP photo under 25 megapixels"))
			picture.load()
			# Re-encode pixels to strip GPS/EXIF metadata and trailing untrusted content.
			clean = io.BytesIO()
			picture.convert("RGB").save(clean, format="JPEG", quality=90)
	except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
		frappe.throw(_("Photo is not a valid image"))
	# File's normal permission check requires equipment write, which technicians intentionally lack.
	# save_file is Frappe's attachment API; the capability and exact tenant/record were checked above.
	from frappe.utils.file_manager import save_file

	file = save_file(
		f"equipment-{frappe.generate_hash(length=12)}.jpg",
		clean.getvalue(),
		EQUIPMENT,
		equipment_id,
		is_private=1,
	)
	return {"file_url": file.file_url}
