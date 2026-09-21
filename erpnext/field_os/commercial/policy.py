"""Versioned pilot plans. Prices are configured independently in Stripe."""

from dataclasses import dataclass
from datetime import date


class EntitlementDenied(PermissionError):
	pass


@dataclass(frozen=True)
class Plan:
	seats: int
	ai: int
	email: int
	sms: int
	features: frozenset[str] = frozenset({"ai", "email", "sms", "agreements", "imports"})


# Initial pilot allowances, not published prices or promises about provider cost.
PLANS = {
	"trial": Plan(10, 500, 1000, 100),
	"standard": Plan(10, 2000, 5000, 500),
	"pro": Plan(50, 10000, 25000, 2500),
	"demo": Plan(10, 100, 0, 0),
}
FEATURES = frozenset({"ai", "email", "sms", "agreements", "imports"})


def period(day: date) -> str:
	return day.strftime("%Y-%m")


def require_access(subscription, feature=None, *, today: date):
	plan = PLANS.get(subscription["plan"])
	if not plan:
		raise EntitlementDenied("Subscription plan is not configured")
	status = subscription["status"]
	if status == "trialing":
		end = subscription.get("trial_end")
		if not end or date.fromisoformat(str(end)[:10]) < today:
			raise EntitlementDenied("Your trial has ended. Choose a plan to continue making changes.")
	elif status == "past_due":
		end = subscription.get("grace_end")
		if not end or date.fromisoformat(str(end)[:10]) < today:
			raise EntitlementDenied(
				"Update your payment method to restore changes and outbound communication."
			)
	elif status != "active":
		raise EntitlementDenied("Subscription is read-only. Open Plan & usage to restore access.")
	if feature and (feature not in plan.features or feature in subscription.get("disabled_features", ())):
		raise EntitlementDenied("This feature is disabled for your company.")
	return plan


def require_quota(plan, metric, used, amount):
	if (
		metric not in {"ai", "email", "sms"}
		or (not isinstance(amount, int) or isinstance(amount, bool))
		or not 1 <= amount <= 100000
	):
		raise ValueError("Invalid usage metric or quantity")
	if used + amount > getattr(plan, metric):
		raise EntitlementDenied(f"Monthly {metric} allowance reached. Open Plan & usage for details.")
