from unittest import TestCase
from unittest.mock import patch

from erpnext.field_os.security.authorization import CapabilityDenied, authorize
from erpnext.field_os.security.context import TenantAccessDenied, TenantContext, resolve_tenant_context
from erpnext.field_os.security.roles import FieldOSRole
from erpnext.field_os.security.scoping import with_company_scope


class TestTenantSecurity(TestCase):
	@patch("erpnext.field_os.security.context.frappe.db.exists", return_value=True)
	@patch("erpnext.field_os.security.context.frappe.get_roles")
	@patch("erpnext.field_os.security.context.frappe.get_all")
	def test_dispatcher_with_company_permission_gets_context(self, get_all, get_roles, _exists):
		get_roles.return_value = [FieldOSRole.DISPATCHER.value]
		get_all.return_value = ["HVAC CO"]
		context = resolve_tenant_context("HVAC CO", "dispatcher@example.test")
		self.assertEqual(context.company, "HVAC CO")
		self.assertIn(FieldOSRole.DISPATCHER, context.roles)

	@patch("erpnext.field_os.security.context.frappe.db.exists", return_value=True)
	@patch("erpnext.field_os.security.context.frappe.get_roles", return_value=[FieldOSRole.DISPATCHER.value])
	@patch("erpnext.field_os.security.context.frappe.get_all", return_value=["OTHER CO"])
	def test_cross_tenant_user_is_denied(self, _get_all, _get_roles, _exists):
		with self.assertRaises(TenantAccessDenied):
			resolve_tenant_context("HVAC CO", "dispatcher@example.test")

	def test_dispatcher_cannot_invoice(self):
		context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		with self.assertRaises(CapabilityDenied):
			authorize(context, "invoice")

	def test_scope_cannot_be_overridden(self):
		context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		with self.assertRaises(PermissionError):
			with_company_scope(context, {"company": "OTHER CO"})

	def test_scope_is_injected(self):
		context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		self.assertEqual(with_company_scope(context, {"status": "Open"})["company"], "HVAC CO")
