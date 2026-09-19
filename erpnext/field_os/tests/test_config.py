from unittest import TestCase
from unittest.mock import patch

from erpnext.field_os.config import FieldOSConfig, FieldOSConfigError


class TestFieldOSConfig(TestCase):
	def test_defaults_are_safe(self):
		with patch.dict("os.environ", {}, clear=True):
			config = FieldOSConfig.from_env()
		self.assertFalse(config.enabled)
		self.assertTrue(config.require_action_approval)
		self.assertEqual(config.model_provider, "disabled")

	def test_production_cannot_disable_approval(self):
		with patch.dict(
			"os.environ",
			{"FIELD_OS_ENVIRONMENT": "production", "FIELD_OS_REQUIRE_ACTION_APPROVAL": "false"},
			clear=True,
		):
			with self.assertRaises(FieldOSConfigError):
				FieldOSConfig.from_env().validate()
