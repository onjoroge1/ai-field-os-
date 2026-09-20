"""Validate and sanitize private completion photos and captured customer signatures."""

import base64
import binascii
import io

import frappe
from frappe import _
from PIL import Image, UnidentifiedImageError

from erpnext.field_os.completions.repository import COMPLETION


def save_image(doc, content, kind):
	if kind not in {"Photo", "Signature"} or not isinstance(content, str) or len(content) > 7000000:
		frappe.throw(_("Choose a photo or signature smaller than 5 MB"))
	try:
		data = base64.b64decode(content, validate=True)
		if len(data) > 5000000:
			frappe.throw(_("Image must be smaller than 5 MB"))
		with Image.open(io.BytesIO(data)) as picture:
			if picture.format not in {"JPEG", "PNG", "WEBP"} or picture.width * picture.height > 25000000:
				frappe.throw(_("Use JPEG, PNG or WebP under 25 megapixels"))
			picture.load()
			background = Image.new("RGBA", picture.size, "white")
			background.alpha_composite(picture.convert("RGBA"))
			pixels = background.convert("RGB")
			if kind == "Signature":
				low, high = pixels.convert("L").getextrema()
				if low > 220 or high - low < 20:
					frappe.throw(_("Draw the customer signature before saving"))
			clean = io.BytesIO()
			pixels.save(clean, format="JPEG", quality=90)
	except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
		frappe.throw(_("Image is not valid"))
	from frappe.utils.file_manager import save_file

	file = save_file(
		f"service-{kind.lower()}-{frappe.generate_hash(length=12)}.jpg",
		clean.getvalue(),
		COMPLETION,
		doc.name,
		is_private=1,
		df="signature" if kind == "Signature" else "photos_json",
	)
	return {"file_url": file.file_url}
