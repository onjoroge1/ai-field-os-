"""Site-wide backup scheduler. Backup bundles and keys are never exposed to tenant APIs."""

import os
import tempfile
import time
from pathlib import Path

import frappe
from frappe.utils import now_datetime

from erpnext.field_os.recovery.bundle import pack
from erpnext.field_os.recovery.crypto import read_key

RUN = "Field OS Recovery Run"


def take_backup(*, proof=None):
	from frappe.utils.backups import BackupGenerator
	from frappe.utils.synchronization import filelock

	if frappe.session.user != "Administrator":
		raise frappe.PermissionError("Backups require the scheduler administrator context")
	read_key()
	configured = os.environ.get("FIELD_OS_BACKUP_DEST", "")
	if not configured or not Path(configured).is_absolute():
		raise ValueError("Configure an absolute backup destination on protected offsite storage")
	destination = Path(configured).resolve()
	site_path = Path(frappe.get_site_path()).resolve()
	if destination == site_path or site_path in destination.parents:
		raise ValueError("Backup destination must be outside the site directory")
	# Our envelope protects all four components and fails closed. Do not invoke the
	# native optional GPG wrapper, which leaves config plaintext and catches failures.
	started = time.monotonic()
	with filelock("field_os_backup", timeout=1), tempfile.TemporaryDirectory(
		prefix="fieldos-backup-"
	) as staging:
		backup = BackupGenerator(
			frappe.conf.db_name,
			frappe.conf.db_user,
			frappe.conf.db_password,
			db_host=frappe.conf.db_host,
			db_port=frappe.conf.db_port,
			db_type=frappe.conf.db_type,
			db_socket=frappe.conf.db_socket,
			backup_path=staging,
			compress_files=True,
		)
		backup.set_backup_file_name()
		backup.take_dump()
		backup.copy_site_config()
		backup.backup_files()
		artifact = pack(
			{
				"database.sql.gz": backup.backup_path_db,
				"public.tgz": backup.backup_path_files,
				"private.tgz": backup.backup_path_private_files,
				"site_config.json": backup.backup_path_conf,
			},
			destination,
			metadata={"site": frappe.local.site, "proof": proof or {}},
		)
		frappe.get_doc(
			{
				"doctype": RUN,
				"kind": "Backup",
				"status": "Succeeded",
				"artifact_id": artifact.name,
				"finished_at": now_datetime(),
				"duration_seconds": time.monotonic() - started,
			}
		).insert(ignore_permissions=True)
		return str(artifact)


def scheduled():
	if not os.environ.get("FIELD_OS_BACKUP_DEST"):
		return  # Installation is inert until a deployment supplies storage and a separate key.
	try:
		take_backup()
	except Exception:
		frappe.get_doc(
			{
				"doctype": RUN,
				"kind": "Backup",
				"status": "Failed",
				"finished_at": now_datetime(),
				"error_code": "backup_failed",
			}
		).insert(ignore_permissions=True)
		frappe.logger("field_os", allow_site=True).error(
			'{"event":"backup","outcome":"error","error_code":"backup_failed"}'
		)


def health():
	from datetime import timedelta

	last = frappe.db.get_value(
		RUN, {"kind": "Backup", "status": "Succeeded"}, "finished_at", order_by="finished_at desc"
	)
	return {
		"configured": bool(os.environ.get("FIELD_OS_BACKUP_DEST")),
		"last_success": last,
		"stale": not last or last < now_datetime() - timedelta(minutes=75),
	}
