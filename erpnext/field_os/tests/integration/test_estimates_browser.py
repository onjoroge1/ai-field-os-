"""Operator → native SMTP queue → customer approval → operator history."""

import json
import os
import queue
import re
import socketserver
import subprocess
import threading
import time
from email import message_from_bytes, policy
from pathlib import Path

import requests

from erpnext.field_os.tests.integration.test_equipment_browser import browser


def run():
	bench = Path.cwd()
	base = "http://127.0.0.1:8000"
	delivered = queue.Queue()

	class SMTP(socketserver.StreamRequestHandler):
		def handle(self):
			self.wfile.write(b"220 fieldos-test SMTP\r\n")
			while line := self.rfile.readline():
				command = line.split(b" ", 1)[0].strip().upper()
				if command == b"DATA":
					self.wfile.write(b"354 End with dot\r\n")
					payload = []
					while (part := self.rfile.readline()) not in (b".\r\n", b""):
						payload.append(part[1:] if part.startswith(b"..") else part)
					delivered.put(b"".join(payload))
					self.wfile.write(b"250 Received\r\n")
				elif command == b"QUIT":
					self.wfile.write(b"221 Bye\r\n")
					break
				else:
					self.wfile.write(b"250 OK\r\n")

	mail = socketserver.TCPServer(("127.0.0.1", 1025), SMTP)
	threading.Thread(target=mail.serve_forever, daemon=True).start()
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
		stdout=(bench / "logs/estimates-web.log").open("w"),
		stderr=subprocess.STDOUT,
	)

	def login():
		browser("cookies", "clear")
		browser("open", base + "/login")
		credentials = json.dumps(
			{"usr": "fieldos-manager@example.invalid", "pwd": os.environ["FIELD_OS_TEST_PASSWORD"]}
		)
		browser(
			"eval",
			"(async () => {const r=await fetch('/api/method/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify("
			+ credentials
			+ ")}); if(!r.ok) throw new Error('Login failed');})()",
		)
		browser("open", base + "/desk/field-os")
		browser("wait", '[data-view="customers"]')
		browser("click", '[data-view="customers"]')
		browser("fill", '[data-role="customer-search"]', "FieldOS Shared")
		browser("wait", "[data-customer]")
		browser("click", "[data-customer]")
		browser("wait", "[data-estimate-list]")

	def dialog():
		browser("wait", "--fn", "Boolean(window.cur_dialog?.display)")

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
		login()
		browser("click", "[data-new-estimate]")
		dialog()
		browser("wait", '.modal.show [data-fieldname="items"] .grid-row')
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "[data-estimate-detail]")
		assert "USD 25.00" in browser("get", "text", "[data-estimate-detail]")
		name = browser("get", "text", "[data-estimate-detail] h2").strip()
		browser("click", "[data-estimate-preview]")
		dialog()
		assert "replenishment" in browser("get", "text", ".modal.show")
		browser("click", ".modal.show .btn-modal-primary")
		browser("wait", "[data-estimate-record-decision]")
		browser("screenshot", str(bench / "logs/estimates-operator.png"))

		subprocess.run(
			[
				str(bench / "env/bin/python"),
				"-m",
				"frappe.utils.bench_helper",
				"frappe",
				"--site",
				"fieldos.test",
				"execute",
				"erpnext.field_os.tests.integration.test_estimates_live.deliver_browser_estimate",
				"--kwargs",
				json.dumps({"estimate_id": name}),
			],
			cwd=bench / "sites",
			check=True,
			timeout=60,
		)
		message = message_from_bytes(delivered.get(timeout=10), policy=policy.default)
		assert message["To"] == "customer@example.invalid"
		body = message.get_body(preferencelist=("html",)).get_content()
		assert "USD 25.00" in body
		token = re.search(r"fieldos-estimate\?token=([A-Za-z0-9_-]+)", body).group(1)
		browser("cookies", "clear")
		browser("open", base + "/fieldos-estimate?token=" + token)
		browser("wait", "#estimate-decision")
		browser("fill", "#approver", "Avery Customer")
		browser("fill", "#comment", "Approved in browser")
		browser("click", 'button[value="Approved"]')
		browser(
			"wait", "--fn", "document.querySelector('#decision-result')?.textContent.includes('approved')"
		)
		browser("screenshot", str(bench / "logs/estimates-customer.png"))
		login()
		browser("wait", f'[data-estimate="{name}"]')
		browser("click", f'[data-estimate="{name}"]')
		browser("wait", "[data-estimate-revise]")
		text = browser("get", "text", "[data-estimate-detail]")
		assert "Avery Customer" in text and "Approved in browser" in text and "Email delivery: Sent" in text
		browser("screenshot", str(bench / "logs/estimates-approved.png"))
		print(
			"Estimate browser acceptance passed: native draft, stock warning, operator approval, SMTP delivery, customer approval, persisted decision and delivery history.",
			flush=True,
		)
	finally:
		try:
			print(browser("snapshot", "-i"), flush=True)
			print(browser("errors"), flush=True)
			print(browser("network", "requests", "--filter", "/api/"), flush=True)
			browser("screenshot", str(bench / "logs/estimates-last-state.png"))
			browser("close")
		finally:
			server.terminate()
			server.wait(timeout=15)
			mail.shutdown()
			mail.server_close()


if __name__ == "__main__":
	run()
