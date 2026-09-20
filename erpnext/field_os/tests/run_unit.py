"""Run isolated Field OS tests without requiring a Frappe site.

Usage: python erpnext/field_os/tests/run_unit.py
Only the import boundaries already patched by unit tests are stubbed. Any
unmocked framework call fails; this runner does not test live persistence.
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path


def unavailable(*args, **kwargs):
	raise RuntimeError("Live Frappe access is unavailable in isolated unit tests")


def main():
	root = Path(__file__).resolve().parents[3]
	sys.path.insert(0, str(root))
	if importlib.util.find_spec("frappe") is None:
		frappe = types.ModuleType("frappe")
		frappe.PermissionError = PermissionError
		frappe.get_all = unavailable
		frappe.get_roles = unavailable
		frappe.db = types.SimpleNamespace(exists=unavailable)
		sys.modules["frappe"] = frappe
		print("Running isolated unit tests with Frappe import stubs.", flush=True)
	suite = unittest.defaultTestLoader.discover(str(root / "erpnext/field_os/tests"), top_level_dir=str(root))
	result = unittest.TextTestRunner(verbosity=1).run(suite)
	return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
	raise SystemExit(main())
