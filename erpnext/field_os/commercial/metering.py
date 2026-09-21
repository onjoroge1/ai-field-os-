"""Meter native mail queue admissions and synchronous provider responses."""

from uuid import uuid4

from erpnext.field_os.commercial.native import consume


class MeteredModel:
	def __init__(self, company, provider):
		self.company, self.provider = company, provider

	def respond(self, messages, tools):
		# Reservation and response commit together. Failed requests roll back the reservation.
		import frappe

		savepoint = "usage_" + uuid4().hex
		frappe.db.savepoint(savepoint)
		try:
			consume(self.company, "ai", str(uuid4()))
			return self.provider.respond(messages, tools)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			raise


class MeteredSender:
	def __init__(self, company, metric, provider):
		self.company, self.metric, self.provider = company, metric, provider

	def send(self, message):
		amount = len(set(message.to + message.cc)) if self.metric == "email" else 1
		consume(self.company, self.metric, message.reference_id, amount=amount)
		return self.provider.send(message)


def native_mail(doc, method=None):
	import frappe

	if doc.reference_doctype in {"Field OS Estimate", "Field OS Work Completion"}:
		company = frappe.db.get_value(doc.reference_doctype, doc.reference_name, "company")
		consume(company, "email", "native:" + doc.name, amount=len(doc.recipients))
