"""Real-browser helpers for disposable GitHub-hosted acceptance sites."""

import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import requests

from erpnext.field_os.tests.integration.test_equipment_browser import browser

BASE = "http://127.0.0.1:8000"


@contextmanager
def running_site(prefix):
	bench = Path.cwd()
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
		stdout=(bench / f"logs/{prefix}-web.log").open("w"),
		stderr=subprocess.STDOUT,
	)
	try:
		deadline = time.monotonic() + 45
		while time.monotonic() < deadline:
			try:
				if requests.get(BASE + "/login", timeout=2).status_code == 200:
					break
			except requests.RequestException:
				pass
			time.sleep(0.5)
		else:
			raise AssertionError("Frappe web server did not become ready")
		yield bench
	finally:
		try:
			print(browser("snapshot", "-i"), flush=True)
			print(browser("errors"), flush=True)
			print(browser("network", "requests", "--filter", "/api/"), flush=True)
			browser("screenshot", str(bench / f"logs/{prefix}-last-state.png"))
			browser("close")
		finally:
			server.terminate()
			server.wait(timeout=15)


def login(user="fieldos-manager@example.invalid"):
	browser("cookies", "clear")
	browser("open", BASE + "/login")
	credentials = json.dumps({"usr": user, "pwd": os.environ["FIELD_OS_TEST_PASSWORD"]})
	browser(
		"eval",
		"(async()=>{const r=await fetch('/api/method/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify("
		+ credentials
		+ ")});if(!r.ok)throw new Error('Login failed');})()",
	)
	browser("open", BASE + "/desk/field-os")
	browser("wait", '[data-view="customers"]')


def customer():
	browser("click", '[data-view="customers"]')
	browser("fill", '[data-role="customer-search"]', "FieldOS Shared")
	browser("wait", "[data-customer]")
	browser("click", "[data-customer]")
	browser("wait", ".field-os__customer-head")
	browser(
		"wait",
		"--fn",
		"!document.querySelector('[data-role=content]')?.textContent.includes('Loading…') && !frappe.ajax_count",
	)


def dialog():
	browser("wait", "--fn", "Boolean(window.cur_dialog?.display)")
