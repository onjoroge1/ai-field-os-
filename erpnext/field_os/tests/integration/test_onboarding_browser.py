"""A company owner configures real locations, staff, service types and readiness in the UI."""

import json
import os

from erpnext.field_os.tests.integration.test_browser_harness import browser, dialog, login, running_site


def run():
	with running_site("onboarding") as bench:
		login("fieldos-owner@example.invalid")
		browser("click", '[data-view="setup"]')
		browser("wait", "[data-setup]")
		browser("click", '[data-setup-step="company"]')
		dialog()
		for key, value in (("address_line1", "100 Test Street"), ("city", "Boston")):
			browser("click", f'.modal.show .grid-body [data-fieldname="{key}"]')
			browser("fill", f'.modal.show .grid-body input[data-fieldname="{key}"]', value)
		browser("click", ".modal.show .modal-title")
		browser("scrollintoview", ".modal.show .btn-modal-primary")
		browser(
			"wait",
			"--fn",
			"!document.querySelector('.modal.show').getAnimations({subtree:true}).some(a => a.playState === 'running')",
		)
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		browser("wait", "--fn", "document.querySelector('[data-setup]')?.textContent.includes('1 locations')")
		browser("click", '[data-setup-step="users"]')
		dialog()
		for key, value in (
			("email", "browser-setup-tech@example.invalid"),
			("first_name", "Avery Technician"),
			("password", os.environ["FIELD_OS_TEST_PASSWORD"]),
			("skills_text", "Heating, Cooling"),
		):
			browser("fill", f'.modal.show input[data-fieldname="{key}"]', value)
		browser("select", '.modal.show select[data-fieldname="gender"]', "Male")
		birth = json.loads(browser("eval", "JSON.stringify(frappe.datetime.str_to_user('1990-01-01'))"))
		if birth.startswith('"'):
			birth = json.loads(birth)
		browser("fill", '.modal.show input[data-fieldname="date_of_birth"]', birth)
		browser("click", ".modal.show .modal-title")
		browser("scrollintoview", ".modal.show .btn-modal-primary")
		browser(
			"wait",
			"--fn",
			"!document.querySelector('.modal.show').getAnimations({subtree:true}).some(a => a.playState === 'running')",
		)
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		browser(
			"wait",
			"--fn",
			"document.querySelector('[data-setup]')?.textContent.includes('1 configured team members')",
		)
		browser("click", '[data-setup-step="services"]')
		dialog()
		browser("click", ".modal.show .modal-title")
		browser("scrollintoview", ".modal.show .btn-modal-primary")
		browser(
			"wait",
			"--fn",
			"!document.querySelector('.modal.show').getAnimations({subtree:true}).some(a => a.playState === 'running')",
		)
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		browser("wait", "--fn", "document.querySelector('[data-setup]')?.textContent.includes('1 services')")
		browser("click", '[data-setup-step="notifications"]')
		dialog()
		browser("fill", '.modal.show input[data-fieldname="invoice_due_days"]', "14")
		browser("click", ".modal.show .modal-title")
		browser("scrollintoview", ".modal.show .btn-modal-primary")
		browser(
			"wait",
			"--fn",
			"!document.querySelector('.modal.show').getAnimations({subtree:true}).some(a => a.playState === 'running')",
		)
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		browser("wait", "[data-setup-finish]:enabled")
		browser("click", "[data-setup-finish]")
		browser("wait", "--fn", "document.querySelector('[data-setup-status]')?.textContent==='Completed'")
		browser("screenshot", str(bench / "logs/onboarding-completed.png"))
		login("browser-setup-tech@example.invalid")
		browser("wait", '[data-view="work"]')
		assert "Company setup" not in browser("get", "text", '[data-role="nav"]')
		browser("click", '[data-view="work"]')
		browser("wait", "[data-work-list]")
		print(
			"Onboarding browser acceptance passed: native locations, technician account, service item, notification defaults, readiness and new technician login.",
			flush=True,
		)


if __name__ == "__main__":
	run()
