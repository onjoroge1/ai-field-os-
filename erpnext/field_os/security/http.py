"""Field OS request budgets and response protections; native auth/CSRF remain in force."""

import hashlib
import os
import time
from uuid import uuid4

import frappe
from frappe import _
from werkzeug.exceptions import RequestEntityTooLarge, ServiceUnavailable, TooManyRequests

PREFIX = "erpnext.field_os."


def endpoint(request, form):
	for prefix in ("/api/method/", "/api/v2/method/"):
		if request.path.startswith(prefix):
			return request.path[len(prefix) :]
	return form.get("cmd", "")


def relevant(request, method):
	return method.startswith(PREFIX) or request.path.startswith(("/desk/field-os", "/field-os-estimate"))


def production():
	return os.environ.get("FIELD_OS_ENVIRONMENT", "development") == "production"


def before_request():
	request = frappe.local.request
	method = endpoint(request, frappe.form_dict)
	if not relevant(request, method):
		return
	frappe.local.field_os_correlation = uuid4().hex
	frappe.local.field_os_started = time.monotonic()
	frappe.local.field_os_endpoint = method
	if production() and (frappe.conf.get("ignore_csrf") or frappe.conf.get("developer_mode")):
		frappe.throw(
			_("Production Field OS requires CSRF checks and developer mode disabled"), frappe.PermissionError
		)
	limit = (
		8 * 1024 * 1024
		if method.endswith((".upload_photo", ".upload_evidence", ".validate_csv"))
		else 1024 * 1024
	)
	if request.content_length and request.content_length > limit:
		raise RequestEntityTooLarge()
	if not method.startswith(PREFIX):
		return
	# A fresh server ID prevents callers from injecting log fields or correlating other users' requests.
	identity = frappe.session.user
	if identity == "Guest":
		identity = request.remote_addr or "unknown"
	bucket = int(time.time() // 60)
	key = "fieldos-rate:" + hashlib.sha256(f"{frappe.local.site}:{identity}:{bucket}".encode()).hexdigest()
	budget = 120 if frappe.session.user == "Guest" else 300
	try:
		pipe = frappe.cache.pipeline(transaction=True)
		count, expiry_set = pipe.incr(key).expire(key, 65).execute()
	except Exception:
		raise ServiceUnavailable("Request admission is temporarily unavailable") from None
	if count > budget:
		raise TooManyRequests(retry_after=60)


def after_request(request, response):
	method = endpoint(request, getattr(frappe, "form_dict", {}) or {})
	if relevant(request, method):
		response.headers["X-Content-Type-Options"] = "nosniff"
		response.headers["X-Frame-Options"] = "DENY"
		response.headers["Referrer-Policy"] = "same-origin"
		response.headers["Cache-Control"] = "no-store"
		response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
		response.headers[
			"Content-Security-Policy"
		] = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
		response.headers["X-Field-OS-Request-ID"] = getattr(frappe.local, "field_os_correlation", uuid4().hex)
	if production():
		response.headers["Strict-Transport-Security"] = "max-age=31536000"
		manager = getattr(frappe.local, "cookie_manager", None)
		if manager:
			for name, cookie in manager.cookies.items():
				cookie["secure"] = True
				if name == "sid":
					cookie.update(httponly=True, samesite="Lax")
