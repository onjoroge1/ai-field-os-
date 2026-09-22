import base64
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from cryptography.exceptions import InvalidTag

from erpnext.field_os.recovery.bundle import FILES, pack, unpack


class BackupBundle(TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)
		key = patch.dict(os.environ, {"FIELD_OS_BACKUP_KEY_B64": base64.b64encode(os.urandom(32)).decode()})
		key.start()
		self.addCleanup(key.stop)
		self.sources = {}
		for label in FILES:
			path = self.root / label
			path.write_bytes(b"private-payload-and-encryption-secret\0" * 100)
			self.sources[label] = path

	def test_all_components_round_trip_and_manifest_is_encrypted(self):
		bundle = pack(self.sources, self.root / "vault", metadata={"proof": "private"})
		self.assertEqual(len(list(bundle.iterdir())), 5)
		for encrypted in bundle.iterdir():
			self.assertNotIn(b"private-payload", encrypted.read_bytes())
		manifest = unpack(bundle, self.root / "restore")
		self.assertEqual(manifest["metadata"]["proof"], "private")
		for label, path in self.sources.items():
			self.assertEqual(path.read_bytes(), (self.root / "restore" / label).read_bytes())

	def test_tampering_fails_without_publishing_partial_plaintext(self):
		bundle = pack(self.sources, self.root / "vault")
		path = bundle / "private.tgz.enc"
		content = bytearray(path.read_bytes())
		content[-20] ^= 1
		path.write_bytes(content)
		with self.assertRaises(InvalidTag):
			unpack(bundle, self.root / "restore")
		self.assertFalse((self.root / "restore").exists())

	def test_wrong_key_and_missing_components_fail_closed(self):
		with self.assertRaises(ValueError):
			pack({"database.sql.gz": self.sources["database.sql.gz"]}, self.root / "vault")
		self.assertFalse(list((self.root / "vault").iterdir()))
		bundle = pack(self.sources, self.root / "vault")
		with patch.dict(os.environ, {"FIELD_OS_BACKUP_KEY_B64": base64.b64encode(os.urandom(32)).decode()}):
			with self.assertRaises(InvalidTag):
				unpack(bundle, self.root / "restore")
		self.assertFalse((self.root / "restore").exists())
