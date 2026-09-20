"""AI prepares the same immutable estimate preview used by the operator UI."""

from dataclasses import replace

from erpnext.field_os.actions.models import RiskClass
from erpnext.field_os.ai.conversation import Citation, ToolOutput
from erpnext.field_os.ai.frappe_store import FrappeCacheProposalStore
from erpnext.field_os.ai.tools import ToolDefinition
from erpnext.field_os.estimates import workflow


def register(registry):
	def prepare(context, args):
		preview = workflow.preview(context, str(args["estimate_id"]))
		store = FrappeCacheProposalStore()
		proposal = store.load(context.company, preview["proposal"]["id"])
		proposal = replace(
			proposal,
			arguments={
				**proposal.arguments,
				"approval_id": proposal.id,
				"recipient": preview["estimate"]["recipient"],
				"total": preview["estimate"]["total"],
				"currency": preview["estimate"]["currency"],
				"shortages": [
					{
						"item_code": row["item_code"],
						"quantity": str(row["quantity"]),
						"available_quantity": str(row["available_quantity"]),
					}
					for row in preview["shortages"]
				],
			},
		)
		store.save(proposal)
		return proposal

	registry.register(
		ToolDefinition(
			"get_estimate",
			"Read an estimate, taxes, total, required parts and recorded customer decisions.",
			"read",
			frozenset({"estimate_id"}),
			lambda context, args: ToolOutput(
				workflow.detail(context.company, str(args["estimate_id"])),
				(Citation("Estimate", "Field OS Estimate", str(args["estimate_id"])),),
			),
		)
	)
	registry.register(
		ToolDefinition(
			"send_estimate",
			"Prepare an estimate email. Sending always requires explicit operator approval.",
			"quote",
			frozenset({"estimate_id"}),
			lambda context, args: workflow.approve(context, args["approval_id"], args["approval_id"]),
			optional_fields=frozenset(
				{"expected_version", "approval_id", "recipient", "total", "currency", "shortages"}
			),
			risk=RiskClass.EXTERNAL,
			prepare=prepare,
		)
	)
