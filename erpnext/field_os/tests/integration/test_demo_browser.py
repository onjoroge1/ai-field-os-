"""Provision, explore and reset a real demo company using its operator guide."""

import os

from erpnext.field_os.tests.integration.test_browser_harness import browser, dialog, login, running_site


def run():
	with running_site("demo") as bench:
		login("Administrator")
		browser("scrollintoview", '[data-view="demo"]')
		browser("click", '[data-view="demo"]')
		browser("wait", "[data-demo-create]")
		browser("click", "[data-demo-create]")
		dialog()
		browser("fill", '.modal.show input[data-fieldname="password"]', os.environ["FIELD_OS_TEST_PASSWORD"])
		browser("click", ".modal.show .modal-title")
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "[data-demo-guide]")
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		assert "Generation 1" in browser("get", "text", "[data-demo-generation]")
		assert "Email and SMS disabled" in browser("get", "text", "[data-demo-banner]")
		browser("screenshot", str(bench / "logs/demo-guide.png"))
		browser("scrollintoview", '[data-demo-action="inbox"]')
		browser("click", '[data-demo-action="inbox"]')
		browser(
			"wait",
			"--fn",
			"document.querySelector('[data-role=thread-pane]')?.textContent.includes('84 degrees')",
		)
		browser("screenshot", str(bench / "logs/demo-inbox.png"))
		browser("scrollintoview", '[data-view="demo"]')
		browser("click", '[data-view="demo"]')
		browser("wait", '[data-demo-action="agreement"]')
		browser("scrollintoview", '[data-demo-action="agreement"]')
		browser("click", '[data-demo-action="agreement"]')
		browser("wait", "[data-agreement-detail]")
		assert "Overdue" in browser("get", "text", "[data-agreement-detail]")
		browser("scrollintoview", '[data-view="demo"]')
		browser("click", '[data-view="demo"]')
		browser("wait", '[data-demo-action="estimate"]')
		browser("scrollintoview", '[data-demo-action="estimate"]')
		browser("click", '[data-demo-action="estimate"]')
		browser("wait", "[data-estimate-detail]")
		assert "synthetic" in browser("get", "text", "[data-estimate-detail]").lower()
		browser("scrollintoview", '[data-view="demo"]')
		browser("click", '[data-view="demo"]')
		browser("wait", "[data-demo-reset]")
		browser("scrollintoview", "[data-demo-reset]")
		browser("click", "[data-demo-reset]")
		dialog()
		assert "posted invoices remain" in browser("get", "text", ".modal.show")
		browser("fill", '.modal.show input[data-fieldname="password"]', os.environ["FIELD_OS_TEST_PASSWORD"])
		browser("click", ".modal.show .modal-title")
		browser("click", ".modal.show .btn-modal-primary")
		browser(
			"wait",
			"--fn",
			"document.querySelector('[data-demo-generation]')?.textContent.includes('Generation 2')",
		)
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		browser("screenshot", str(bench / "logs/demo-reset.png"))
		print(
			"Demo browser acceptance passed: company provisioning, synthetic Inbox, overdue maintenance, sample approval and explicitly approved fresh generation.",
			flush=True,
		)


if __name__ == "__main__":
	run()
