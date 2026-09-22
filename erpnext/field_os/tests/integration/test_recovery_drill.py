"""Create a NEW disposable site, restore a verified encrypted bundle, validate business probes."""

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from erpnext.field_os.recovery.bundle import unpack


def command(*arguments):
	result = subprocess.run(["bench", *arguments], check=False, text=True, capture_output=True, timeout=600)
	if result.returncode:
		# No environment, configuration or credentials enter the report.
		print(result.stdout[-6000:])
		print(result.stderr[-6000:])
		raise RuntimeError("Disposable restore command failed")
	return result.stdout


def run():
	if os.environ.get("FIELD_OS_RECOVERY_DRILL") != "1":
		raise RuntimeError("Explicit disposable recovery drill mode is required")
	bench = Path.cwd()
	source, target = "fieldos.test", "fieldos-restore.test"
	if (bench / "sites" / target).exists():
		raise RuntimeError("Refusing to overwrite an existing restore site")
	root_password = os.environ["FIELD_OS_TEST_DB_ROOT_PASSWORD"]
	with tempfile.TemporaryDirectory(prefix="fieldos-recovery-drill-") as temporary:
		root = Path(temporary)
		os.environ["FIELD_OS_BACKUP_KEY_B64"] = base64.b64encode(os.urandom(32)).decode()
		os.environ["FIELD_OS_BACKUP_DEST"] = str(root / "vault")
		command(
			"--site",
			source,
			"execute",
			"erpnext.field_os.tests.integration.test_recovery_live.prepare",
			"--kwargs",
			json.dumps({"descriptor": str(root / "descriptor.json")}),
		)
		artifact = json.loads((root / "descriptor.json").read_text())["artifact"]
		started = time.monotonic()
		stage = root / "verified"
		unpack(artifact, stage)
		command(
			"new-site",
			target,
			"--db-type",
			"mariadb",
			"--db-host",
			"127.0.0.1",
			"--mariadb-user-host-login-scope",
			"%",
			"--db-root-password",
			root_password,
			"--admin-password",
			"disposable-restore-test",
		)
		config_path = bench / "sites" / target / "site_config.json"
		config = json.loads(config_path.read_text())
		saved = json.loads((stage / "site_config.json").read_text())
		# Keep NEW database credentials; retain only the original application encryption key.
		config.update(allow_tests=True, pause_scheduler=True, mute_emails=True, disable_scheduler=True)
		config["encryption_key"] = saved["encryption_key"]
		config_path.write_text(json.dumps(config))
		os.chmod(config_path, 0o600)
		command(
			"--site",
			target,
			"restore",
			str(stage / "database.sql.gz"),
			"--db-root-password",
			root_password,
			"--with-public-files",
			str(stage / "public.tar.gz"),
			"--with-private-files",
			str(stage / "private.tar.gz"),
			"--force",
		)
		command("--site", target, "migrate")
		result = command(
			"--site",
			target,
			"execute",
			"erpnext.field_os.tests.integration.test_recovery_live.verify",
			"--kwargs",
			json.dumps({"manifest_path": str(stage / "manifest.json")}),
		)
		report = {
			"result": "passed",
			"restore_seconds": round(time.monotonic() - started, 2),
			"target": target,
			"checks": ["database", "public_archive", "private_file", "application_key", "tenant_permissions"],
			"scope": "disposable CI fixture; production RPO/RTO unverified",
		}
		assert '"verified": true' in result.lower(), "Restore verification did not return success"
		(bench / "logs/recovery-drill.json").write_text(json.dumps(report, indent=2))
		print(json.dumps(report))


if __name__ == "__main__":
	run()
