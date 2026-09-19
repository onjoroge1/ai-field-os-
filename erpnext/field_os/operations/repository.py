"""Data boundary for exception-first operator views."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from erpnext.field_os.operations.models import AttentionItem, SearchResult


class OperationsRepository(Protocol):
	def list_attention(self, company: str, day: date, limit: int) -> list[AttentionItem]:
		...

	def search(self, company: str, query: str, limit: int) -> list[SearchResult]:
		...
