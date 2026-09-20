from datetime import UTC, datetime, timedelta
from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine, ActionRejected
from erpnext.field_os.actions.models import ActionProposal, RiskClass


class TestActionEngine(TestCase):
	def proposal(self, risk=RiskClass.EXTERNAL):
		now = datetime.now(UTC)
		return ActionProposal(
			"P1", "send_message", {}, risk, "HVAC CO", "d@example.test", now, now + timedelta(minutes=5)
		)

	def test_external_action_requires_approval(self):
		with self.assertRaises(ActionRejected):
			ActionEngine().execute(self.proposal(), "key-1", lambda: "sent")

	def test_idempotency_prevents_duplicate_side_effect(self):
		engine = ActionEngine()
		calls = []
		proposal = self.proposal()
		first = engine.execute(
			proposal, "key-1", lambda: calls.append("sent") or "sent", approved_by="manager@example.test"
		)
		second = engine.execute(
			proposal, "key-1", lambda: calls.append("duplicate"), approved_by="manager@example.test"
		)
		self.assertEqual(first, second)
		self.assertEqual(calls, ["sent"])

	def test_stale_proposal_is_rejected(self):
		now = datetime.now(UTC)
		proposal = ActionProposal("P1", "send", {}, RiskClass.EXTERNAL, "HVAC CO", "d", now, now)
		with self.assertRaises(ActionRejected):
			ActionEngine().execute(proposal, "key", lambda: True, approved_by="m", now=now)

	def test_idempotency_is_scoped_by_tenant_actor_and_tool(self):
		engine = ActionEngine()
		first = self.proposal(RiskClass.LOW)
		second = ActionProposal(
			"P2",
			"send_message",
			{},
			RiskClass.LOW,
			"OTHER CO",
			"d@example.test",
			first.created_at,
			first.expires_at,
		)
		self.assertEqual(engine.execute(first, "shared", lambda: "first").result, "first")
		self.assertEqual(engine.execute(second, "shared", lambda: "second").result, "second")

	def test_reusing_idempotency_key_for_different_arguments_is_rejected(self):
		engine = ActionEngine()
		first = self.proposal(RiskClass.LOW)
		engine.execute(first, "same-key", lambda: "first")
		changed = ActionProposal(
			"P2",
			first.tool,
			{"thread_id": "THREAD-2"},
			first.risk,
			first.company,
			first.actor,
			first.created_at,
			first.expires_at,
		)
		with self.assertRaises(ActionRejected):
			engine.execute(changed, "same-key", lambda: "second")
