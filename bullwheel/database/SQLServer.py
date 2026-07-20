# Copyright (c) 2026 Bonneville Ridge LLC

import frappe
import pymssql
from frappe.utils import CallbackManager, recursive_defaultdict
from frappe.utils.password import get_decrypted_password

from bullwheel.database.exceptions import ConnectionError, QueryError, TransactionError


class MSSQLDatabase:
	"""
	SQL Server database handler for Barrie's external server connections.
	Mirrors the interface style of frappe.database.database.Database
	without inheriting its MariaDB-coupled implementation.

	Required
	"""

	# ─── Class-Level Constants ────────────────────────────────────────

	VARCHAR_LENGTH = 255
	MAX_COLUMN_LENGTH = 128  # SQL Server's actual column name length limit

	# ─── Initialization ───────────────────────────────────────────────

	def __init__(
		self,
		server_document,
		timeout: int = 10,
	):
		self.server = server_document.server_name
		self.username = server_document.username
		self.password = get_decrypted_password("SQL Server", server_document.name, fieldname="password")
		self.current_database = server_document.database_name
		self.timeout = timeout
		self.connection = None
		self.cursor = None

		self.transaction_write_count = 0

		# Callback managers mirror frappe.db's hook system, allowing external
		# code to register functions that fire at transaction boundaries.
		self.before_commit = CallbackManager()
		self.after_commit = CallbackManager()
		self.before_rollback = CallbackManager()
		self.after_rollback = CallbackManager()

		# Value cache mirrors frappe.db.value_cache for short-lived result caching.
		self.value_cache = recursive_defaultdict()

		self.logger = frappe.logger("mssql")

	# ─── Connection Lifecycle ─────────────────────────────────────────

	def connect(self) -> None:
		"""Open a connection to the SQL Server instance using the credentials
		provided at initialization, raising a ConnectionError if the attempt fails."""
		try:
			self.connection = pymssql.connect(
				server=self.server,
				user=self.username,
				password=self.password,
				database=self.current_database,
				timeout=self.timeout,
				encryption='require',
			)
			self.cursor = self.connection.cursor(as_dict=False)
		except pymssql.OperationalError as error:
			raise ConnectionError(f"Failed to connect to server '{self.server}': {error}") from error

	def close(self) -> None:
		"""Close the active database connection and reset the connection
		and cursor attributes to None, mirroring frappe.db.close()."""
		if self.connection:
			self.connection.close()
			self.cursor = None
			self.connection = None

	def __enter__(self):
		"""Open the connection when entering a `with` block, returning self
		so the handler is accessible via the `as` clause."""
		self.connect()
		return self

	def __exit__(self, exception_type, exception_value, traceback):
		"""On exiting a `with` block, commit if no exception occurred or
		rollback if one did, then close the connection in either case."""
		if exception_type:
			self.rollback()
		else:
			self.commit()
		self.close()

	# ─── Core Query Execution ─────────────────────────────────────────

	def sql(
		self,
		query: str,
		values: tuple | list | dict = (),
		*,
		as_dict: bool,
		debug: bool = False,
		auto_commit: bool = False,
		pluck: bool = False,
	) -> list:
		"""Execute a raw SQL query against the active connection and return
		results in the requested format, mirroring the signature of frappe.db.sql().
		Connects automatically if no active connection exists."""
		if not self.connection:
			self.connect()

		if not isinstance(values, tuple | list | dict):
			values = (values,)

		if debug:
			self.logger.warning(f"Executing query: {query} | Values: {values}")

		try:
			self.cursor = self.connection.cursor(as_dict=as_dict)
			self.cursor.execute(query, values or None)

			if auto_commit:
				self.commit()

			if not self.cursor.description:
				return []

			result = self.cursor.fetchall()

			if pluck:
				return [row[0] for row in result]

			if not as_dict:
				return [[value for value in row] for row in result]

			return result

		except pymssql.DatabaseError as error:
			raise QueryError(f"Query execution failed: {error}\nQuery: {query}") from error

	# ─── Transaction Management ───────────────────────────────────────

	def begin(self) -> None:
		"""Disable autocommit on the active connection to begin an explicit
		transaction, mirroring frappe.db.begin()."""
		if self.connection:
			self.connection.autocommit(False)

	def commit(self) -> None:
		"""Commit the current transaction, fire registered commit callbacks,
		and clear the value cache, mirroring frappe.db.commit()."""
		if not self.connection:
			return
		try:
			self.before_commit.run()
			self.connection.commit()
			self.value_cache.clear()
			self.after_commit.run()
		except pymssql.DatabaseError as error:
			raise TransactionError(f"Commit failed: {error}") from error

	def rollback(self) -> None:
		"""Roll back the current transaction, fire registered rollback callbacks,
		and clear the value cache, mirroring frappe.db.rollback()."""
		if not self.connection:
			return
		try:
			self.before_rollback.run()
			self.connection.rollback()
			self.value_cache.clear()
			self.after_rollback.run()
		except pymssql.DatabaseError as error:
			raise TransactionError(f"Rollback failed: {error}") from error

	# ─── Health Check ─────────────────────────────────────────────────

	def test_connection(self) -> str:
		"""Attempt to open a connection and execute a minimal query to verify
		that the server is reachable and credentials are valid. Always closes
		the connection before returning."""
		try:
			self.connect()
			self.sql(
				query="SELECT 1",
				as_dict=False
			)
			return 'success'
		except (ConnectionError, QueryError) as error:
			return error
		finally:
			self.close()

