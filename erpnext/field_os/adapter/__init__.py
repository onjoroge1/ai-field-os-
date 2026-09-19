"""ERP system adapter contracts."""

from erpnext.field_os.adapter.base import FieldOperationsAdapter
from erpnext.field_os.adapter.erpnext import ERPNextAdapter

__all__ = ["ERPNextAdapter", "FieldOperationsAdapter"]
