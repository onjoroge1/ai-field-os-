"""Create → activate → dispatch recurring service → renew through the operator UI."""

from erpnext.field_os.tests.integration.test_browser_harness import (
	browser,
	customer,
	dialog,
	login,
	running_site,
)


def run():
	with running_site("agreements") as bench:
		login()
		customer()
		browser("wait", "[data-new-agreement]")
		browser("click", "[data-new-agreement]")
		dialog()
		browser("fill", '.modal.show input[data-fieldname="interval_months"]', "3")
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "[data-activate-agreement]")
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		name = browser("get", "text", "[data-agreement-detail] h2").strip()
		browser("click", "[data-activate-agreement]")
		browser("wait", "[data-schedule-visit]")
		assert browser("get", "count", "[data-schedule-visit]").strip() == "4"
		browser("click", "tbody tr:first-child [data-schedule-visit]")
		dialog()
		browser("click", ".modal.show .btn-modal-primary")
		browser(
			"wait",
			"--fn",
			"document.querySelector('[data-agreement-detail]')?.textContent.includes('MAT-MVS-')",
		)
		browser("screenshot", str(bench / "logs/agreements-scheduled.png"))
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		browser("click", "[data-renew-agreement]")
		dialog()
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "[data-activate-agreement]")
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		assert browser("get", "text", "[data-agreement-detail] h2").strip() != name
		browser("click", '[data-view="agreements"]')
		browser("wait", "[data-agreement-dashboard]")
		assert name in browser("get", "text", "[data-agreement-dashboard]")
		browser("screenshot", str(bench / "logs/agreements-dashboard.png"))
		print(
			"Agreements browser acceptance passed: draft, activation, four recurring visits, native dispatch job, renewal and dashboard.",
			flush=True,
		)


if __name__ == "__main__":
	run()
