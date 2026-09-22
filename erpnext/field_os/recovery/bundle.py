"""Publish complete encrypted bundles and stage verified restore inputs. No database restore here."""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from erpnext.field_os.recovery.crypto import checksum, decrypt, encrypt, read_key

FILES = ("database.sql.gz", "public.tar.gz", "private.tar.gz", "site_config.json")


def pack(sources, destination, *, metadata=None):
	key = read_key()  # Fail before any plaintext is copied or a success marker exists.
	root = Path(destination)
	root.mkdir(parents=True, exist_ok=True, mode=0o700)
	run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
	pending = root / ("." + run_id + ".pending")
	pending.mkdir(mode=0o700)
	try:
		if set(sources) != set(FILES):
			raise ValueError("All database, file and configuration backups are required")
		manifest = {
			"version": 1,
			"run_id": run_id,
			"created_at": datetime.now(UTC).isoformat(),
			"key_id": hashlib.sha256(key).hexdigest()[:16],
			"files": {},
			"metadata": metadata or {},
		}
		for label in FILES:
			source = Path(sources[label])
			if not source.is_file() or source.is_symlink() or source.stat().st_size == 0:
				raise ValueError("Missing or empty backup component")
			encrypt(source, pending / (label + ".enc"), key, label)
			manifest["files"][label] = {"sha256": checksum(source), "size": source.stat().st_size}
		with tempfile.TemporaryDirectory(prefix="fieldos-manifest-") as temporary:
			path = Path(temporary) / "manifest.json"
			path.write_text(json.dumps(manifest, sort_keys=True))
			os.chmod(path, 0o600)
			encrypt(path, pending / "manifest.enc", key, "manifest")
		# Publication is a single rename on the destination filesystem. Readers ignore .pending.
		pending.rename(root / run_id)
		return root / run_id
	except Exception:
		shutil.rmtree(pending)
		raise


def unpack(source, destination):
	key = read_key()
	source, destination = Path(source), Path(destination)
	if source.name.startswith(".") or destination.exists():
		raise ValueError("Use a complete bundle and a new restore directory")
	destination.mkdir(parents=True, mode=0o700)
	try:
		decrypt(source / "manifest.enc", destination / "manifest.json", key, "manifest")
		manifest = json.loads((destination / "manifest.json").read_text())
		if manifest.get("version") != 1 or set(manifest.get("files", {})) != set(FILES):
			raise ValueError("Unsupported backup manifest")
		for label in FILES:
			path = destination / label
			decrypt(source / (label + ".enc"), path, key, label)
			if (
				path.stat().st_size != manifest["files"][label]["size"]
				or checksum(path) != manifest["files"][label]["sha256"]
			):
				raise ValueError("Backup content verification failed")
		return manifest
	except Exception:
		shutil.rmtree(destination)
		raise


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(
		description="Verify and decrypt a Field OS backup into a NEW private directory"
	)
	parser.add_argument("source")
	parser.add_argument("destination")
	arguments = parser.parse_args()
	unpack(arguments.source, arguments.destination)
	print("Backup verified and staged. Follow the restore runbook before starting services.")
