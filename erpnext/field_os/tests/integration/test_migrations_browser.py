"""Upload and review CSVs, use imported customer equipment, and explicitly roll back."""

from erpnext.field_os.tests.integration.test_browser_harness import browser, dialog, login, running_site
from erpnext.field_os.tests.integration.test_migrations_live import CUSTOMERS, EQUIPMENT, SITES
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER


def run():
	with running_site("migrations") as bench:
		login(OWNER)
		batches = []
		for kind, content in (("customers", CUSTOMERS), ("sites", SITES), ("equipment", EQUIPMENT)):
			browser("click", '[data-view="imports"]')
			browser("wait", "[data-import-home]")
			browser("select", "[data-import-kind]", kind)
			file = bench / f"logs/import-{kind}.csv"
			file.write_text(content)
			browser("upload", "[data-import-file]", str(file))
			browser("click", "[data-import-validate]")
			browser("wait", "[data-import-apply]")
			assert "Validated" in browser("get", "text", "[data-import-status]")
			batches.append(browser("get", "text", "[data-import-detail] h2").strip())
			browser("screenshot", str(bench / f"logs/migrations-{kind}-preview.png"))
			browser("click", "[data-import-apply]")
			dialog()
			browser("click", ".modal.show .btn-modal-primary")
			browser("wait", "[data-import-rollback]")
			browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
			assert "Applied" in browser("get", "text", "[data-import-status]")
		browser("click", '[data-view="customers"]')
		browser("fill", '[data-role="customer-search"]', "Migration Avery")
		browser("wait", "[data-customer]")
		browser("click", "[data-customer]")
		browser(
			"wait",
			"--fn",
			"document.querySelector('[data-role=content]')?.textContent.includes('Imported heat pump')",
		)
		browser("screenshot", str(bench / "logs/migrations-customer.png"))
		for name in reversed(batches):
			browser("click", '[data-view="imports"]')
			browser("wait", f'[data-import-batch="{name}"]')
			browser("scrollintoview", f'[data-import-batch="{name}"]')
			browser("click", f'[data-import-batch="{name}"]')
			browser("wait", "[data-import-rollback]")
			browser("click", "[data-import-rollback]")
			dialog()
			assert "permanently removes" in browser("get", "text", ".modal.show")
			browser("click", ".modal.show .btn-modal-primary")
			browser(
				"wait",
				"--fn",
				"document.querySelector('[data-import-status]')?.textContent.includes('Rolled Back')",
			)
			browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
		browser("screenshot", str(bench / "logs/migrations-rollback.png"))
		print(
			"Migration browser acceptance passed: three CSV uploads, reviewed native imports, searchable customer equipment and approved rollback.",
			flush=True,
		)


if __name__ == "__main__":
	run()
