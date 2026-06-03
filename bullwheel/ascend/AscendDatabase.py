# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe
from bullwheel.database.SQLServer import MSSQLDatabase

def get_default_ascend_database():
		default_database = frappe.db.get_single_value('Bullwheel Settings', 'default_database')
		return frappe.get_doc("SQL Server", default_database)

class AscendDatabase:
	"""
	Ascend RMS query handler for Bullwheel virtual DocTypes.

	Wraps MSSQLDatabase and provides high-level query methods that understand
	Ascend-specific conventions: field-to-column mapping, bracket-quoted column
	names, Frappe filter formats, OFFSET...FETCH pagination, and OR LIKE search
	across configurable search columns.

	Usage mirrors MSSQLDatabase — use as a context manager:

	    with AscendDatabase(server_document) as ascend:
	        products = ascend.get_list(
	            PRODUCT_TABLE, SELECT_CLAUSE, "ID", FIELD_TO_COLUMN,
	            filters=filters, search_columns=SEARCH_COLUMNS, ...
	        )
	"""

	def __init__(self, server_document):
		"""Initialize with a SQL Server Frappe document from the SQL Server DocType."""
		self._server_document = server_document
		self._database = None

	def __enter__(self):
		"""Open the underlying MSSQLDatabase connection."""
		self._database = MSSQLDatabase(server_document=self._server_document)
		self._database.connect()
		return self

	def __exit__(self, exception_type, exception_value, traceback):
		"""Delegate commit/rollback/close to the underlying MSSQLDatabase."""
		self._database.__exit__(exception_type, exception_value, traceback)

	# ─── High-Level Query Methods ─────────────────────────────────────────────

	def get_record(self, table, select_clause, id_column, record_id):
		"""Fetch a single record by its primary key, returning a fieldname-keyed dict.
		Returns None if no matching record exists."""
		result = self._database.sql(
			f"SELECT {select_clause} FROM {table} WHERE {id_column} = %s",
			[record_id],
			as_dict=True,
		)
		return result[0] if result else None

	def get_list(
		self,
		table,
		select_clause,
		id_column,
		field_to_column,
		filters=None,
		search_columns=None,
		page_length=20,
		start=0,
		txt=None,
		or_filters=None,
	):
		"""Fetch a paginated, optionally filtered list of records.
		Pagination uses SQL Server's OFFSET...FETCH syntax. Returns a list of
		fieldname-keyed dicts."""
		where_clause, values = self._build_where_clause(
			field_to_column, filters, search_columns, txt, or_filters
		)
		query = (
			f"SELECT {select_clause} FROM {table}"
			f"{where_clause}"
			f" ORDER BY {id_column} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
		)
		values += [start or 0, page_length or 20]
		return self._database.sql(query, values, as_dict=True)

	def count_records(
		self,
		table,
		field_to_column,
		filters=None,
		search_columns=None,
		txt=None,
		or_filters=None,
	):
		"""Return the count of records matching the given filters and search text."""
		where_clause, values = self._build_where_clause(
			field_to_column, filters, search_columns, txt, or_filters
		)
		query = f"SELECT COUNT(*) FROM {table}{where_clause}"
		result = self._database.sql(query, values)
		return result[0][0] if result else 0

	def record_exists(self, table, id_column, record_id):
		"""Return True if a record with the given primary key value exists in the table."""
		result = self._database.sql(
			f"SELECT TOP 1 {id_column} FROM {table} WHERE {id_column} = %s",
			[record_id],
		)
		return bool(result)

	# ─── Internal Helpers ─────────────────────────────────────────────────────

	@staticmethod
	def _extract_search_text(txt, or_filters):
		"""Return the raw search string from either a direct txt arg or Frappe's or_filters list."""
		if txt:
			return txt
		if or_filters:
			for filter_condition in or_filters:
				if len(filter_condition) >= 4 and filter_condition[2].lower() == "like":
					return filter_condition[3].strip("%")
		return None

	@staticmethod
	def _build_where_clause(field_to_column, filters, search_columns, txt, or_filters):
		"""Build a parameterized SQL WHERE clause from Frappe list-view filters and search text.

		Handles both dict-format ({fieldname: value}) and list-format
		([[doctype, fieldname, operator, value]]) filters. Supported operators:
		=, !=, <, <=, >, >=, LIKE, NOT LIKE, IN, NOT IN. Fieldnames are resolved
		to SQL column names via field_to_column. Unrecognised fieldnames are skipped.

		When search text is present (from txt or or_filters), appends an OR LIKE
		condition across all search_columns.
		"""
		conditions = []
		values = []

		if filters:
			filter_list = (
				[[None, fieldname, "=", value] for fieldname, value in filters.items()]
				if isinstance(filters, dict)
				else filters
			)
			for filter_item in filter_list:
				fieldname = filter_item[1]
				operator = filter_item[2]
				value = filter_item[3]

				column = field_to_column.get(fieldname)
				if not column:
					continue

				sql_operator = operator.upper()

				if sql_operator in ("IN", "NOT IN"):
					placeholders = ", ".join(["%s"] * len(value))
					conditions.append(f"{column} {sql_operator} ({placeholders})")
					values.extend(value)
				else:
					conditions.append(f"{column} {sql_operator} %s")
					values.append(value)

		search_text = AscendDatabase._extract_search_text(txt, or_filters)
		if search_text and search_columns:
			search_conditions = " OR ".join(f"{column} LIKE %s" for column in search_columns)
			conditions.append(f"({search_conditions})")
			pattern = f"%{search_text}%"
			values.extend([pattern] * len(search_columns))

		where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
		return where_clause, values
