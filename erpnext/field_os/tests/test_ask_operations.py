from unittest import TestCase

from erpnext.field_os.actions.engine import ActionEngine
from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.ai.conversation import (
	AskOperationsService,
	Citation,
	ConversationRetention,
	MemoryConversationStore,
	ToolOutput,
)
from erpnext.field_os.ai.provider import ModelReply
from erpnext.field_os.ai.tools import ToolDefinition, ToolRegistry, ToolValidationError
from erpnext.field_os.security.context import TenantContext
from erpnext.field_os.security.roles import FieldOSRole


class FakeProvider:
	def __init__(self, reply):
		self.reply = reply
		self.messages = ()

	def respond(self, messages, tools):
		self.messages = messages
		return self.reply


class ProposalSink:
	def __init__(self):
		self.items = {}

	def save(self, proposal):
		self.items[(proposal.company, proposal.id)] = proposal

	def load(self, company, proposal_id):
		return self.items.get((company, proposal_id))

	def delete(self, company, proposal_id):
		self.items.pop((company, proposal_id), None)


class TestAskOperations(TestCase):
	def setUp(self):
		self.context = TenantContext("HVAC CO", "d@example.test", frozenset({FieldOSRole.DISPATCHER}))
		self.store = MemoryConversationStore()

	def test_read_tool_returns_server_generated_citations(self):
		registry = ToolRegistry()
		registry.register(
			ToolDefinition(
				"lookup",
				"Lookup",
				"read",
				frozenset({"id"}),
				lambda _context, args: ToolOutput({"id": args["id"]}, (Citation("Job 1", "Issue", "JOB-1"),)),
			)
		)
		provider = FakeProvider(
			ModelReply("Here is the job.", {"tool": "lookup", "arguments": {"id": "JOB-1"}})
		)
		response = AskOperationsService(provider, registry, self.store).ask(self.context, "Find job 1")
		self.assertEqual(response.citations[0].record_id, "JOB-1")
		self.assertEqual(provider.messages[-1].content, "Find job 1")

	def test_external_tool_becomes_preview_without_execution(self):
		calls = []
		registry = ToolRegistry()
		registry.register(
			ToolDefinition(
				"send_update",
				"Send update",
				"communicate",
				frozenset({"message"}),
				lambda _context, _args: calls.append("sent"),
				risk=RiskClass.EXTERNAL,
			)
		)
		sink = ProposalSink()
		provider = FakeProvider(
			ModelReply("Send this update?", {"tool": "send_update", "arguments": {"message": "On our way"}})
		)
		response = AskOperationsService(provider, registry, self.store, sink).ask(self.context, "Tell them")
		self.assertEqual(calls, [])
		self.assertEqual(response.approval.risk, RiskClass.EXTERNAL)
		self.assertEqual(next(iter(sink.items.values())).company, "HVAC CO")

		service = AskOperationsService(provider, registry, self.store, sink)
		# Recreate a proposal in the service-owned sink, then approve it once.
		response = service.ask(self.context, "Tell them")
		receipt = service.approve(self.context, response.approval.proposal_id, "approve:1", ActionEngine())
		self.assertEqual(receipt.status, "executed")
		self.assertEqual(calls, ["sent"])

	def test_none_retention_does_not_keep_history(self):
		provider = FakeProvider(ModelReply("Done"))
		service = AskOperationsService(provider, ToolRegistry(), self.store)
		response = service.ask(self.context, "Hello", retention=ConversationRetention.NONE)
		self.assertEqual(self.store.load("HVAC CO", "d@example.test", response.conversation_id), ())

	def test_extra_tool_arguments_are_rejected(self):
		registry = ToolRegistry()
		registry.register(ToolDefinition("lookup", "Lookup", "read", frozenset({"id"}), lambda _c, _a: True))
		provider = FakeProvider(
			ModelReply("", {"tool": "lookup", "arguments": {"id": "1", "company": "OTHER"}})
		)
		with self.assertRaises(ToolValidationError):
			AskOperationsService(provider, registry, self.store).ask(self.context, "Find it")
