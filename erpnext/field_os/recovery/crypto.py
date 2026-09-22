"""Versioned, streaming AES-256-GCM envelopes. Plaintext is never published on failure."""

import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"FIELDOS-BACKUP-1\n"
CHUNK = 1024 * 1024


def read_key():
	try:
		key = base64.b64decode(os.environ["FIELD_OS_BACKUP_KEY_B64"], validate=True)
	except (KeyError, ValueError) as exc:
		raise ValueError("Configure a base64 encoded 32-byte backup key") from exc
	if len(key) != 32:
		raise ValueError("Backup key must contain exactly 32 bytes")
	return key


def checksum(path):
	with Path(path).open("rb") as handle:
		return hashlib.file_digest(handle, "sha256").hexdigest()


def encrypt(source, destination, key, label):
	source, destination = Path(source), Path(destination)
	if destination.exists():
		raise FileExistsError("Encrypted output already exists")
	nonce = os.urandom(12)
	header = MAGIC + nonce
	cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
	cipher.authenticate_additional_data(header + label.encode())
	try:
		with source.open("rb") as reader, destination.open("xb") as writer:
			os.chmod(destination, 0o600)
			writer.write(header)
			while chunk := reader.read(CHUNK):
				writer.write(cipher.update(chunk))
			writer.write(cipher.finalize())
			writer.write(cipher.tag)
			writer.flush()
			os.fsync(writer.fileno())
	except Exception:
		destination.unlink(missing_ok=True)
		raise


def decrypt(source, destination, key, label):
	source, destination = Path(source), Path(destination)
	if destination.exists():
		raise FileExistsError("Restore output already exists")
	temporary = destination.with_name(destination.name + ".partial")
	try:
		with source.open("rb") as reader:
			header = reader.read(len(MAGIC) + 12)
			if not header.startswith(MAGIC) or source.stat().st_size < len(header) + 16:
				raise ValueError("Invalid backup envelope")
			reader.seek(-16, 2)
			tag = reader.read(16)
			cipher = Cipher(algorithms.AES(key), modes.GCM(header[-12:], tag)).decryptor()
			cipher.authenticate_additional_data(header + label.encode())
			reader.seek(len(header))
			remaining = source.stat().st_size - len(header) - 16
			with temporary.open("xb") as writer:
				os.chmod(temporary, 0o600)
				while remaining:
					chunk = reader.read(min(CHUNK, remaining))
					if not chunk:
						raise ValueError("Truncated backup")
					remaining -= len(chunk)
					writer.write(cipher.update(chunk))
				writer.write(cipher.finalize())
				writer.flush()
				os.fsync(writer.fileno())
		temporary.rename(destination)
	except Exception:
		temporary.unlink(missing_ok=True)
		raise
