"""Runtime configuration for AI Field OS."""

from __future__ import annotations

import os
from dataclasses import dataclass


class FieldOSConfigError(RuntimeError):
	pass


def _bool(name: str, default: bool = False) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FieldOSConfig:
	enabled: bool
	environment: str
	model_provider: str
	require_action_approval: bool

	@classmethod
	def from_env(cls) -> FieldOSConfig:
		return cls(
			enabled=_bool("FIELD_OS_ENABLED", False),
			environment=os.getenv("FIELD_OS_ENVIRONMENT", "development").strip().lower(),
			model_provider=os.getenv("FIELD_OS_MODEL_PROVIDER", "disabled").strip().lower(),
			require_action_approval=_bool("FIELD_OS_REQUIRE_ACTION_APPROVAL", True),
		)

	def validate(self) -> None:
		if self.environment not in {"development", "test", "staging", "production"}:
			raise FieldOSConfigError("FIELD_OS_ENVIRONMENT must be development, test, staging, or production")
		if self.environment == "production" and not self.require_action_approval:
			raise FieldOSConfigError("production cannot disable FIELD_OS_REQUIRE_ACTION_APPROVAL")
