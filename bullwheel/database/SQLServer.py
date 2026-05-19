# Copyright (c) 2026 Bonneville Ridge LLC

import frappe
import pymssql
from frappe.utils import CallbackManager, recursive_defaultdict

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
		server: str,
		username: str,
		password: str,
		database: str,
		timeout: int = 10,
	):
		self.server = server
		self.username = username
		self.password = password
		self.current_database = database
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
		as_dict: bool = False,
		as_list: bool = False,
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

			if as_list and not as_dict:
				return [[value for value in row] for row in result]

			return result

		except pymssql.DatabaseError as error:
			raise QueryError(f"Query execution failed: {error}\nQuery: {query}") from error

	# ─── High-Level Query Methods ─────────────────────────────────────

	def get_value(
		self,
		table: str,
		filters: dict | str,
		fieldname: str | list = "*",
		as_dict: bool = False,
		debug: bool = False,
	):
		"""Fetch a single value or row from the given table matching the
		provided filters, mirroring frappe.db.get_value(). Returns None if
		no matching record is found."""
		fields = fieldname if isinstance(fieldname, list) else [fieldname]
		columns = ", ".join(fields) if fieldname != "*" else "*"
		resolved_filters = filters if isinstance(filters, dict) else {"name": filters}
		where_clause, where_values = self._build_where_clause(resolved_filters)

		query = f"SELECT TOP 1 {columns} FROM {table} WHERE {where_clause}"
		result = self.sql(query, where_values, as_dict=as_dict, debug=debug)

		if not result:
			return None

		row = result[0]

		if as_dict or isinstance(fieldname, list) or fieldname == "*":
			return row

		return row[0] if not as_dict else row.get(fieldname)

	def get_all(
		self,
		table: str,
		filters: dict = None,
		fields: list = None,
		order_by: str = None,
		limit: int = None,
		as_dict: bool = True,
		debug: bool = False,
	) -> list:
		"""Fetch all rows from the given table matching the provided filters,
		mirroring frappe.db.get_all(). Returns an empty list if no rows match."""
		query, values = self._build_select_query(table, filters, fields, order_by, limit)
		return self.sql(query, values, as_dict=as_dict, debug=debug)

	def exists(self, table: str, filters: dict | str) -> bool:
		"""Return True if at least one record matching the given filters exists
		in the table, mirroring frappe.db.exists()."""
		result = self.get_value(table, filters, fieldname="1")
		return result is not None

	def count(self, table: str, filters: dict = None, debug: bool = False) -> int:
		"""Return the number of rows in the given table matching the provided
		filters, mirroring frappe.db.count()."""
		where_clause, values = self._build_where_clause(filters) if filters else ("1=1", ())
		query = f"SELECT COUNT(*) FROM {table} WHERE {where_clause}"
		result = self.sql(query, values, debug=debug)
		return result[0][0] if result else 0

	def insert(self, table: str, values: dict) -> None:
		"""Insert a single row into the given table using the provided column-value
		dictionary, mirroring frappe.db.insert()."""
		columns = ", ".join(values.keys())
		placeholders = ", ".join(["%s"] * len(values))
		query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
		self.sql(query, tuple(values.values()), as_dict=False)

	def set_value(self, table: str, filters: dict | str, field: str, value=None) -> None:
		"""Update a single field on all rows matching the given filters,
		mirroring frappe.db.set_value()."""
		resolved_filters = filters if isinstance(filters, dict) else {"name": filters}
		where_clause, where_values = self._build_where_clause(resolved_filters)
		query = f"UPDATE {table} SET {field} = %s WHERE {where_clause}"
		self.sql(query, (value,) + where_values, as_dict=False)

	def delete(self, table: str, filters: dict) -> None:
		"""Delete all rows from the given table matching the provided filters,
		mirroring frappe.db.delete()."""
		where_clause, values = self._build_where_clause(filters)
		query = f"DELETE FROM {table} WHERE {where_clause}"
		self.sql(query, values, as_dict=False)

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

	def test_connection(self) -> bool:
		"""Attempt to open a connection and execute a minimal query to verify
		that the server is reachable and credentials are valid. Always closes
		the connection before returning."""
		try:
			self.connect()
			self.sql("SELECT 1")
			return True
		except ConnectionError, QueryError:
			return False
		finally:
			self.close()

	# ─── Internal Helpers ─────────────────────────────────────────────

	def _build_where_clause(self, filters: dict) -> tuple[str, tuple]:
		"""Convert a dictionary of column-value pairs into a parameterized SQL
		WHERE clause string and a tuple of the corresponding values."""
		if not filters:
			return "1=1", ()
		clause = " AND ".join([f"{column} = %s" for column in filters.keys()])
		return clause, tuple(filters.values())

	def _build_select_query(
		self,
		table: str,
		filters: dict = None,
		fields: list = None,
		order_by: str = None,
		limit: int = None,
	) -> tuple[str, tuple]:
		"""Construct a parameterized SELECT query from the provided table name,
		filters, field list, ordering, and row limit. Uses SQL Server's TOP
		syntax rather than LIMIT, which is not supported by SQL Server."""
		columns = ", ".join(fields) if fields else "*"
		top_clause = f"TOP {limit} " if limit else ""
		query = f"SELECT {top_clause}{columns} FROM {table}"
		values = ()

		if filters:
			where_clause, values = self._build_where_clause(filters)
			query += f" WHERE {where_clause}"

		if order_by:
			query += f" ORDER BY {order_by}"

		return query, values
