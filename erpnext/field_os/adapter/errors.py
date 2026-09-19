class AdapterError(RuntimeError):
	"""Base error for ERP adapter failures."""


class RecordNotFound(AdapterError):
	pass


class AdapterUnavailable(AdapterError):
	pass
