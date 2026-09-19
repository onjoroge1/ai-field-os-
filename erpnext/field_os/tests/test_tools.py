from unittest import TestCase

from erpnext.field_os.ai.intent import parse_tool_call
from erpnext.field_os.ai.tools import ToolDefinition, ToolRegistry, ToolValidationError
from erpnext.field_os.security.authorization import CapabilityDenied
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class TestToolRegistry(TestCase):
	def setUp(self):
		self.context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		self.registry = ToolRegistry()
		self.registry.register(
			ToolDefinition("lookup", "lookup", "read", frozenset({"id"}), lambda context, args: (context.company, args["id"]))
		)

	def test_validates_schema_before_handler(self):
		with self.assertRaises(ToolValidationError):
			self.registry.invoke(self.context, "lookup", {})

	def test_unknown_tool_is_rejected(self):
		with self.assertRaises(ToolValidationError):
			self.registry.invoke(self.context, "drop_database", {})

	def test_capability_is_enforced_outside_model(self):
		registry = ToolRegistry()
		registry.register(ToolDefinition("bill", "bill", "invoice", frozenset(), lambda _c, _a: True))
		with self.assertRaises(CapabilityDenied):
			registry.invoke(self.context, "bill", {})

	def test_model_payload_rejects_extra_control_fields(self):
		with self.assertRaises(ValueError):
			parse_tool_call({"tool": "lookup", "arguments": {"id": "1"}, "capability": "admin"})
