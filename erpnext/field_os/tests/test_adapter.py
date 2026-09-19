from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from erpnext.field_os.adapter.erpnext import ERPNextAdapter
from erpnext.field_os.adapter.errors import RecordNotFound


class TestERPNextAdapter(TestCase):
	def setUp(self):
		self.adapter = ERPNextAdapter()

	@patch("erpnext.field_os.adapter.erpnext.frappe.get_all")
	def test_get_customer_normalizes_record(self, get_all):
		get_all.return_value = [
			SimpleNamespace(
				name="CUST-1", customer_name="ABC Dental", email_id="ops@example.test", mobile_no="555"
			)
		]
		record = self.adapter.get_customer("CUST-1")
		self.assertEqual(record.id, "CUST-1")
		self.assertEqual(record.name, "ABC Dental")
		self.assertEqual(record.email, "ops@example.test")

	@patch("erpnext.field_os.adapter.erpnext.frappe.get_all")
	def test_missing_customer_raises_normalized_error(self, get_all):
		get_all.return_value = []
		with self.assertRaises(RecordNotFound):
			self.adapter.get_customer("missing")

	@patch("erpnext.field_os.adapter.erpnext.frappe.get_all")
	def test_list_invoices_normalizes_money(self, get_all):
		get_all.return_value = [
			SimpleNamespace(name="INV-1", status="Overdue", outstanding_amount=125.50, currency="USD")
		]
		rows = self.adapter.list_invoices("CUST-1")
		self.assertEqual(str(rows[0].outstanding_amount), "125.5")
