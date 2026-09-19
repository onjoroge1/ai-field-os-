"""Role-neutral application service for Today and global search."""

from __future__ import annotations

from datetime import UTC, date, datetime

from erpnext.field_os.operations.models import AttentionSeverity, SearchResult, TodaySnapshot
from erpnext.field_os.operations.repository import OperationsRepository
from erpnext.field_os.security.authorization import authorize
from erpnext.field_os.security.context import TenantContext

_SEVERITY_ORDER = {
	AttentionSeverity.CRITICAL: 0,
	AttentionSeverity.WARNING: 1,
	AttentionSeverity.INFO: 2,
}


class OperationsService:
	def __init__(self, repository: OperationsRepository) -> None:
		self.repository = repository

	def today(
		self,
		context: TenantContext,
		*,
		day: date | None = None,
		limit: int = 50,
	) -> TodaySnapshot:
		authorize(context, "read")
		day = day or datetime.now(UTC).date()
		limit = max(1, min(limit, 100))
		items = self.repository.list_attention(context.company, day, limit)
		items.sort(
			key=lambda item: (
				_SEVERITY_ORDER[item.severity],
				item.due_at or datetime.max.replace(tzinfo=UTC),
				item.id,
			)
		)
		items = items[:limit]
		counts: dict[str, int] = {"total": len(items)}
		for item in items:
			counts[item.kind] = counts.get(item.kind, 0) + 1
			counts[item.severity.value] = counts.get(item.severity.value, 0) + 1
		return TodaySnapshot(context.company, day, counts, tuple(items))

	def search(self, context: TenantContext, query: str, *, limit: int = 20) -> list[SearchResult]:
		authorize(context, "read")
		query = query.strip()
		if len(query) < 2:
			return []
		return self.repository.search(context.company, query, max(1, min(limit, 50)))
