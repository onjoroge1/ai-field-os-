"""Owner plan screen and role-aware navigation on the real operator shell."""

from erpnext.field_os.tests.integration.test_browser_harness import browser, login, running_site
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER


def run():
	with running_site("commercial") as bench:
		login(OWNER)
		browser("snapshot", "-i")
		browser("click", '[data-view="commercial"]')
		browser("wait", "[data-plan-summary]")
		text = browser("get", "text", "[data-plan-summary]")
		assert "trial" in text and "Allowance" in text, text
		browser("screenshot", str(bench / "logs/commercial-owner.png"))
		login()
		assert browser("get", "count", '[data-view="commercial"]').strip() == "0"


if __name__ == "__main__":
	run()
