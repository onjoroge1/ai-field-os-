"""Bind external-send approval to the exact immutable message preview."""

import hashlib
import json
from dataclasses import asdict


def message_digest(message):
	values = asdict(message)
	for key in ("delivery_state", "error", "external_id", "dedupe_key", "classification"):
		values.pop(key, None)
	return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
