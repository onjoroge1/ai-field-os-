"""A technician signs off work; billing posts it and sends the actual queued invoice."""

import json
import queue
import socketserver
import subprocess
import threading
from email import message_from_bytes, policy

from PIL import Image

from erpnext.field_os.tests.integration.test_browser_harness import browser, dialog, login, running_site


def run():
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

	with socketserver.TCPServer(("127.0.0.1", 1025), SMTP) as smtp:
		threading.Thread(target=smtp.serve_forever, daemon=True).start()
		try:
			with running_site("completions") as bench:
				seed = subprocess.run(
					[
						str(bench / "env/bin/python"),
						"-m",
						"frappe.utils.bench_helper",
						"frappe",
						"--site",
						"fieldos.test",
						"execute",
						"erpnext.field_os.tests.integration.test_completions_live.seed_browser",
					],
					cwd=bench / "sites",
					check=True,
					capture_output=True,
					text=True,
					timeout=90,
				)
				job = json.loads(seed.stdout.strip().splitlines()[-1])["job"]
				login("fieldos-tech@example.invalid")
				browser("click", '[data-view="work"]')
				browser("wait", f'[data-start-work="{job}"]')
				browser("click", f'[data-start-work="{job}"]')
				browser("wait", "[data-work-edit]")
				name = browser("get", "text", "[data-work-detail] h2").strip()
				browser("click", "[data-work-edit]")
				dialog()
				browser(
					"fill",
					'.modal.show textarea[data-fieldname="summary"]',
					"Replaced filter, tested heating and cleaned the work area",
				)
				for key in ("safety_checks", "operational_test", "work_area_clean"):
					browser("check", f'.modal.show input[data-fieldname="{key}"]')
				browser("click", '.modal.show .grid-body [data-fieldname="rate"]')
				browser("fill", '.modal.show .grid-body input[data-fieldname="rate"]', "20")
				browser("click", '.modal.show .grid-body [data-fieldname="warehouse"]')
				browser("select", '.modal.show .grid-body select[data-fieldname="warehouse"]', "Stores - FIA")
				photo = bench / "logs/completions-photo.png"
				Image.new("RGB", (120, 80), "steelblue").save(photo)
				browser("upload", "[data-work-photos]", str(photo))
				browser("fill", '.modal.show input[data-fieldname="signer_name"]', "Avery Customer")
				browser("wait", ".modal.show .signature-field canvas")
				browser("scrollintoview", ".modal.show .signature-field canvas")
				bounds = json.loads(
					browser(
						"eval",
						"JSON.stringify((()=>{const r=document.querySelector('.modal.show .signature-field canvas').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})())",
					)
				)
				if isinstance(bounds, str):
					bounds = json.loads(bounds)
				x, y = round(bounds["x"]), round(bounds["y"])
				browser("mouse", "move", str(x + 20), str(y + 70))
				browser("mouse", "down")
				for dx, dy in ((40, 30), (65, 60), (95, 20), (135, 70), (185, 45)):
					browser("mouse", "move", str(x + dx), str(y + dy))
				browser("mouse", "up")
				browser("wait", "--fn", "window.cur_dialog.get_value('signature')?.startsWith('data:image/')")
				browser("click", ".modal.show .btn-modal-primary")
				browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
				browser("wait", '[data-work-detail] img[alt="Customer signature"]')
				browser("click", "[data-work-complete]")
				dialog()
				browser("click", ".modal.show .btn-modal-primary")
				browser(
					"wait",
					"--fn",
					"document.querySelector('[data-work-detail]')?.textContent.includes('Completed by')",
				)
				browser("screenshot", str(bench / "logs/completions-technician.png"))
				login("fieldos-billing@example.invalid")
				browser("click", '[data-view="work"]')
				browser("wait", f'[data-work="{name}"]')
				browser("click", f'[data-work="{name}"]')
				browser("wait", "[data-work-invoice]")
				browser("click", "[data-work-invoice]")
				dialog()
				browser(
					"select",
					'.modal.show select[data-fieldname="tax_template"]',
					"FieldOS Service Tax 10% - FIA",
				)
				browser("click", ".modal.show .btn-modal-primary")
				browser(
					"wait",
					"--fn",
					"document.querySelector('.modal.show .btn-modal-primary')?.textContent.includes('Approve and post')",
				)
				dialog()
				assert "USD 22.00" in browser("get", "text", ".modal.show")
				browser("click", ".modal.show .btn-modal-primary")
				browser("wait", '[data-work-notice="Invoice"]')
				browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
				browser("click", '[data-work-notice="Invoice"]')
				dialog()
				browser("click", ".modal.show .btn-modal-primary")
				browser(
					"wait",
					"--fn",
					"document.querySelector('.modal.show .btn-modal-primary')?.textContent.includes('Approve and send')",
				)
				dialog()
				assert "customer@example.invalid" in browser("get", "text", ".modal.show")
				browser("click", ".modal.show .btn-modal-primary")
				browser(
					"wait",
					"--fn",
					"document.querySelector('[data-work-detail]')?.textContent.includes('Not Sent')",
				)
				subprocess.run(
					[
						str(bench / "env/bin/python"),
						"-m",
						"frappe.utils.bench_helper",
						"frappe",
						"--site",
						"fieldos.test",
						"execute",
						"erpnext.field_os.tests.integration.test_completions_live.deliver_browser_notice",
						"--kwargs",
						json.dumps({"completion_id": name}),
					],
					cwd=bench / "sites",
					check=True,
					timeout=60,
				)
				message = message_from_bytes(delivered.get(timeout=10), policy=policy.default)
				assert message["To"] == "customer@example.invalid"
				body = message.get_body(preferencelist=("html",)).get_content()
				assert "FieldOS Filter" in body and "USD 22.00" in body
				browser("wait", "--fn", "!document.querySelector('.modal-backdrop')")
				browser("click", "[data-work-reload]")
				browser(
					"wait",
					"--fn",
					"document.querySelector('[data-work-detail]')?.textContent.includes(' · Sent · ')",
				)
				browser("screenshot", str(bench / "logs/completions-billing.png"))
				print(
					"Completion browser acceptance passed: assigned technician evidence and signature, native visit completion, billing approval, posted invoice and SMTP delivery.",
					flush=True,
				)
		finally:
			smtp.shutdown()


if __name__ == "__main__":
	run()
