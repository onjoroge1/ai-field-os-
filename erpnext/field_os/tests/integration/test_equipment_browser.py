"""Browser acceptance for a seeded, disposable bench; invoked by Field OS CI.

Uses agent-browser against a real Frappe HTTP server and real operator accounts.
Database fixtures are prepared separately by test_equipment_live.seed_browser.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image


def browser(*args):
	result = subprocess.run(
		["agent-browser", "--session", "fieldos-equipment", *args], capture_output=True, text=True, timeout=60
	)
	if result.returncode:
		raise AssertionError(f"Browser {args[0]} failed: {result.stdout}\n{result.stderr}")
	return result.stdout.strip()


def run():
	bench = Path.cwd()
	base = "http://127.0.0.1:8000"
	server = subprocess.Popen(
		[
			str(bench / "env/bin/python"),
			"-m",
			"frappe.utils.bench_helper",
			"frappe",
			"--site",
			"fieldos.test",
			"serve",
			"--noreload",
			"--port",
			"8000",
		],
		cwd=bench / "sites",
		stdout=(bench / "logs/equipment-web.log").open("w"),
		stderr=subprocess.STDOUT,
	)

	def login(user):
		browser("cookies", "clear")
		browser("open", base + "/login")
		credentials = json.dumps({"usr": user, "pwd": os.environ["FIELD_OS_TEST_PASSWORD"]})
		browser(
			"eval",
			"(async () => { const r = await fetch('/api/method/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify("
			+ credentials
			+ ")}); if(!r.ok) throw new Error('Operator login failed'); return r.status; })()",
		)
		browser("open", base + "/desk/field-os")
		browser("wait", '[data-view="customers"]')
		print(browser("snapshot", "-i"), flush=True)

	def customer():
		browser("click", '[data-view="customers"]')
		browser("fill", '[data-role="customer-search"]', "FieldOS Shared")
		browser("wait", "[data-customer]")
		browser("click", "[data-customer]")
		browser("wait", ".field-os__customer-head")
		print(browser("snapshot", "-i"), flush=True)

	def open_equipment():
		customer()
		browser("find", "text", "Browser heat pump", "click")
		browser("wait", '[data-action="equipment-note"]')

	try:
		deadline = time.monotonic() + 45
		while time.monotonic() < deadline:
			try:
				if requests.get(base + "/login", timeout=2).status_code == 200:
					break
			except requests.RequestException:
				pass
			time.sleep(0.5)
		else:
			raise AssertionError("Frappe web server did not become ready")
		login("fieldos-manager@example.invalid")
		customer()
		browser("click", '[data-action="new-equipment"]')
		browser("fill", '[data-fieldname="equipment_name"] input', "Browser heat pump")
		browser("fill", '[data-fieldname="unit_type"] input', "Heat pump")
		browser("fill", '[data-fieldname="serial_number"] input', "SN-UI-16")
		browser("click", ".modal.show .modal-footer .btn-primary")
		browser("wait", ".field-os__equipment-details")
		assert "SN-UI-16" in browser("get", "text", ".field-os__equipment-details")
		browser("screenshot", str(bench / "logs/equipment-manager.png"))

		login("fieldos-tech@example.invalid")
		open_equipment()
		browser("click", '[data-action="equipment-note"]')
		browser("fill", '[data-fieldname="note"] textarea', "Browser inspection: replaced filter")
		photo = bench / "logs/equipment-upload.png"
		Image.new("RGB", (32, 32), "blue").save(photo)
		browser("upload", "[data-equipment-photos]", str(photo))
		browser(
			"wait",
			"--fn",
			"document.querySelector('[data-upload-status]')?.textContent.includes('1 photos uploaded')",
		)
		browser("click", ".modal.show .modal-footer .btn-primary")
		browser("wait", ".field-os__equipment-photos img")
		browser("reload")
		browser("wait", '[data-view="customers"]')
		open_equipment()
		assert "Browser inspection: replaced filter" in browser("get", "text", ".field-os__equipment-notes")
		browser("wait", "--fn", "document.querySelector('.field-os__equipment-photos img')?.naturalWidth > 0")
		browser(
			"eval",
			"localStorage.setItem('equipment-test-photo', document.querySelector('.field-os__equipment-photos img').getAttribute('src'))",
		)
		browser("screenshot", str(bench / "logs/equipment-technician.png"))
		print(browser("snapshot", "-i"), flush=True)

		login("fieldos-other@example.invalid")
		browser(
			"eval",
			"(async () => { const r=await fetch(localStorage.getItem('equipment-test-photo')); if(r.status !== 403) throw new Error('Another company can access private equipment photo: '+r.status); return 'Private photo denied'; })()",
		)
		print(
			"Browser acceptance passed: manager create, technician note/photo, reload persistence, cross-company file denial.",
			flush=True,
		)
	finally:
		try:
			browser("screenshot", str(bench / "logs/equipment-last-state.png"))
			browser("close")
		finally:
			server.terminate()
			server.wait(timeout=15)


if __name__ == "__main__":
	run()
