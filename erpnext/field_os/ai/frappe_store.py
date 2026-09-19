"""Tenant-bound cache stores for conversations and short-lived proposals."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

import frappe

from erpnext.field_os.actions.models import ActionProposal, RiskClass
from erpnext.field_os.ai.conversation import ConversationRetention
from erpnext.field_os.ai.provider import ModelMessage


def _conversation_key(company: str, user: str, conversation_id: str) -> str:
	return f"field-os:conversation:{company}:{user}:{conversation_id}"


class FrappeCacheConversationStore:
	def load(self, company, user, conversation_id):
		raw = frappe.cache.get_value(_conversation_key(company, user, conversation_id))
		if not raw:
			return ()
		payload = json.loads(raw)
		return tuple(ModelMessage(item["role"], item["content"]) for item in payload)

	def save(self, company, user, conversation_id, messages, retention):
		key = _conversation_key(company, user, conversation_id)
		if retention == ConversationRetention.NONE:
			frappe.cache.delete_value(key)
			return
		ttl = 8 * 60 * 60 if retention == ConversationRetention.SESSION else 30 * 24 * 60 * 60
		frappe.cache.set_value(key, json.dumps([asdict(item) for item in messages]), expires_in_sec=ttl)

	def clear(self, company, user, conversation_id):
		frappe.cache.delete_value(_conversation_key(company, user, conversation_id))


class FrappeCacheProposalStore:
	def save(self, proposal: ActionProposal) -> None:
		payload = asdict(proposal)
		payload["risk"] = proposal.risk.value
		payload["created_at"] = proposal.created_at.isoformat()
		payload["expires_at"] = proposal.expires_at.isoformat()
		frappe.cache.set_value(
			f"field-os:proposal:{proposal.company}:{proposal.id}",
			json.dumps(payload),
			expires_in_sec=10 * 60,
		)

	def load(self, company: str, proposal_id: str) -> ActionProposal | None:
		raw = frappe.cache.get_value(f"field-os:proposal:{company}:{proposal_id}")
		if not raw:
			return None
		payload = json.loads(raw)
		if payload.get("company") != company:
			return None
		return ActionProposal(
			id=payload["id"],
			tool=payload["tool"],
			arguments=payload["arguments"],
			risk=RiskClass(payload["risk"]),
			company=payload["company"],
			actor=payload["actor"],
			created_at=datetime.fromisoformat(payload["created_at"]),
			expires_at=datetime.fromisoformat(payload["expires_at"]),
		)

	def delete(self, company: str, proposal_id: str) -> None:
		frappe.cache.delete_value(f"field-os:proposal:{company}:{proposal_id}")
