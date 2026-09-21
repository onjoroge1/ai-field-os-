import hashlib
import unittest
from unittest.mock import patch
from uuid import uuid4

import frappe
from werkzeug.exceptions import RequestEntityTooLarge, TooManyRequests
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from erpnext.field_os.security import http


class LiveHTTP(unittest.TestCase):
	def test_api_versions_share_atomic_guest_budget(self):
		identity = "test-" + uuid4().hex
		original_user = frappe.session.user
		original_request = getattr(frappe.local, "request", None)
		original_form = getattr(frappe.local, "form_dict", None)
		bucket = 1
		key = (
			"fieldos-rate:" + hashlib.sha256(f"{frappe.local.site}:{identity}:{bucket}".encode()).hexdigest()
		)
		try:
			frappe.set_user("Guest")
			frappe.local.form_dict = frappe._dict()
			with patch.object(http.time, "time", return_value=60):
				for index in range(120):
					version = "/api/method/" if index % 2 else "/api/v2/method/"
					frappe.local.request = Request(
						EnvironBuilder(
							path=version + "erpnext.field_os.api.health.health",
							environ_base={"REMOTE_ADDR": identity},
						).get_environ()
					)
					http.before_request()
				with self.assertRaises(TooManyRequests):
					http.before_request()
		finally:
			frappe.cache.delete(key)
			frappe.local.request, frappe.local.form_dict = original_request, original_form
			frappe.set_user(original_user)

	def test_oversized_api_payload_is_rejected(self):
		original_request = getattr(frappe.local, "request", None)
		original_form = getattr(frappe.local, "form_dict", None)
		try:
			frappe.local.form_dict = frappe._dict()
			frappe.local.request = Request(
				EnvironBuilder(
					path="/api/method/erpnext.field_os.api.ask.ask",
					method="POST",
					data=b"x" * (1024 * 1024 + 1),
				).get_environ()
			)
			with self.assertRaises(RequestEntityTooLarge):
				http.before_request()
		finally:
			frappe.local.request, frappe.local.form_dict = original_request, original_form


def run():
	if not frappe.conf.allow_tests:
		raise RuntimeError("Use a disposable site with allow_tests enabled")
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(LiveHTTP)
	)
	if not result.wasSuccessful():
		raise AssertionError("HTTP admission acceptance failed")
	return {"passed": result.testsRun}
