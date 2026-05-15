class SQLServerException(Exception):
	"""Base exception for all SQL Server errors."""

	pass


class ConnectionError(SQLServerException):
	"""Raised when a connection cannot be established."""

	pass


class QueryError(SQLServerException):
	"""Raised when a query fails."""

	pass


class TransactionError(SQLServerException):
	"""Raised when a transaction operation fails."""

	pass
