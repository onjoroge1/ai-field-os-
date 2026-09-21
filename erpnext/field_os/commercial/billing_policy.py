"""Pure mapping of current Stripe subscription state to product access."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit


def hosted_url(value, host):
	parsed = urlsplit(value or "")
	if (
		parsed.scheme != "https"
		or parsed.hostname != host
		or parsed.username
		or parsed.password
		or parsed.port
	):
		raise ValueError("Unexpected billing provider URL")
	return value


def subscription_values(remote, prices, current, now):
	items = remote.get("items", {}).get("data", [])
	if len(items) != 1 or items[0].get("quantity") != 1:
		raise ValueError("A Field OS subscription must have one configured plan")
	price = items[0].get("price", {}).get("id")
	plan = next((name for name, price_id in prices.items() if price_id == price), None)
	if not plan:
		raise ValueError("Subscription price is not in the Field OS price catalog")
	status = remote.get("status")
	status = status if status in {"active", "trialing", "past_due", "canceled"} else "suspended"
	grace_end = None
	if status == "past_due":
		grace_end = current.get("grace_end") if current.get("status") == "past_due" else None
		grace_end = grace_end or (now.date() + timedelta(days=7)).isoformat()
	trial_end = remote.get("trial_end")
	period_end = items[0].get("current_period_end")
	return {
		"plan": plan,
		"status": status,
		"grace_end": grace_end,
		"trial_end": datetime.fromtimestamp(trial_end, UTC).date().isoformat()
		if trial_end
		else current.get("trial_end"),
		"billing_period_end": datetime.fromtimestamp(period_end, UTC).replace(tzinfo=None)
		if period_end
		else None,
		"stripe_subscription": remote["id"],
	}
