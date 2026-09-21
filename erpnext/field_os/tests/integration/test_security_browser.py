"""Exercise native session/CSRF and Field OS HTTP hardening in a real browser."""

from erpnext.field_os.tests.integration.test_browser_harness import browser, login, running_site


def run():
	with running_site("security"):
		login()
		browser(
			"eval",
			"""(async()=>{
			const r=await fetch('/api/method/erpnext.field_os.api.health.health');
			if(!r.ok || r.headers.get('X-Content-Type-Options')!=='nosniff' || r.headers.get('X-Frame-Options')!=='DENY' || r.headers.get('Cache-Control')!=='no-store') throw new Error('Response hardening missing');
			if(!/^[a-f0-9]{32}$/.test(r.headers.get('X-Field-OS-Request-ID')||'')) throw new Error('Correlation ID missing');
			const denied=await fetch('/api/method/erpnext.field_os.api.equipment.save_equipment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({company:frappe.defaults.get_default('company')})});
			if(![400,403].includes(denied.status)) throw new Error('Mutation without CSRF token was not rejected');
		})()""",
		)
		print(
			"Security browser acceptance: session request headers and missing-CSRF rejection passed.",
			flush=True,
		)


if __name__ == "__main__":
	run()
