"""Normalize provider timestamps and ignore stale delivery transitions."""

from datetime import UTC, datetime

from erpnext.field_os.communications.models import DeliveryState


def timestamp(value):
	value = datetime.fromisoformat(value) if isinstance(value, str) else value
	return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def accept_delivery(message, event):
	previous = message.metadata.get("delivery_event_at")
	if previous and timestamp(event.occurred_at) <= timestamp(previous):
		return False
	if message.delivery_state in {DeliveryState.DELIVERED, DeliveryState.BOUNCED, DeliveryState.FAILED}:
		return event.state == message.delivery_state
	return True
