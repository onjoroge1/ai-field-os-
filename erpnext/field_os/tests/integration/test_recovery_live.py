"""Restore probes are available only on explicitly disposable test sites."""

import hashlib
import json
import secrets
from pathlib import Path

import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from erpnext.field_os.recovery.service import take_backup
from erpnext.field_os.tests.integration.test_equipment_live import COMPANY_A, COMPANY_B
from erpnext.field_os.tests.integration.test_onboarding_live import OWNER

DOCTYPES = (
	"Company",
	"Customer",
	"Field OS HVAC Equipment",
	"Field OS Estimate",
	"Sales Invoice",
	"Field OS Usage",
)


def guard():
	if not frappe.conf.allow_tests or not frappe.local.site.endswith(".test"):
		raise RuntimeError("Recovery drills require a disposable .test site with allow_tests")


def prepare(descriptor):
	guard()
	content = secrets.token_bytes(64)
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "recovery-probe.txt",
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Company",
			"attached_to_name": COMPANY_A,
		}
	).save(ignore_permissions=True)
	credential = secrets.token_hex(32)
	set_encrypted_password("User", OWNER, credential, "api_secret")
	# The independent dump connection must see the fixture and encrypted credential.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	proof = {
		"counts": {doctype: frappe.db.count(doctype) for doctype in DOCTYPES},
		"companies": [COMPANY_A, COMPANY_B],
		"file_name": file.name,
		"file_sha256": hashlib.sha256(content).hexdigest(),
		"user": OWNER,
		"credential_sha256": hashlib.sha256(credential.encode()).hexdigest(),
	}
	artifact = take_backup(proof=proof)
	Path(descriptor).write_text(json.dumps({"artifact": artifact}))


def verify(manifest_path):
	guard()
	manifest = json.loads(Path(manifest_path).read_text())
	proof = manifest["metadata"]["proof"]
	for doctype, count in proof["counts"].items():
		assert frappe.db.count(doctype) == count, "Restored row count differs: " + doctype
	for company in proof["companies"]:
		assert frappe.db.exists("Company", company)
	file = frappe.get_doc("File", proof["file_name"])
	assert file.is_private and file.attached_to_name == COMPANY_A
	assert hashlib.sha256(file.get_content()).hexdigest() == proof["file_sha256"]
	credential = get_decrypted_password("User", proof["user"], "api_secret")
	assert hashlib.sha256(credential.encode()).hexdigest() == proof["credential_sha256"]
	from erpnext.field_os.security.context import resolve_tenant_context

	assert resolve_tenant_context(COMPANY_A, user=OWNER).company == COMPANY_A
	try:
		resolve_tenant_context(COMPANY_B, user=OWNER)
	except frappe.PermissionError:
		pass
	else:
		raise AssertionError("Restored tenant permissions leaked")
	return {
		"verified": True,
		"counts": proof["counts"],
		"private_file": True,
		"credential": True,
		"tenant_isolation": True,
	}
