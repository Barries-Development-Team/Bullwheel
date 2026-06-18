# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import re

import frappe
from frappe.model.document import Document
from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.ascend.schema_config_builder import (
	build_field_to_column,
	build_search_columns,
	build_select_clause,
	find_primary_key_field,
	normalize_record,
)

# ─── Static Helper Functions ───────────────────────────────────────

def get_default_ascend_database():
		default_database = frappe.db.get_single_value('Bullwheel Settings', 'default_database')
		return frappe.get_doc("SQL Server", default_database)

def _extract_search_text(txt, or_filters):
		"""Return the raw search string from either a direct txt arg or Frappe's or_filters list."""
		if txt:
			return txt
		if or_filters:
			for filter_condition in or_filters:
				if len(filter_condition) >= 4 and filter_condition[2].lower() == "like":
					return filter_condition[3].strip("%")
		return None

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

	search_text = _extract_search_text(txt, or_filters)
	if search_text and search_columns:
		search_conditions = " OR ".join(f"{column} LIKE %s" for column in search_columns)
		conditions.append(f"({search_conditions})")
		pattern = f"%{search_text}%"
		values.extend([pattern] * len(search_columns))

	where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
	return where_clause, values


class AbstractVirtualDocType(Document):

	# ─── Subclass Contract — override these ───────────────────────────────────
	TABLE_NAME: str = None           # Ascend SQL table name, e.g. Products"
	JOIN_CLAUSES: str = None	# Complete Join clause(s) as string.
	# PRIMARY_KEY_COLUMN: str = None  # SQL primary key column name, e.g. "ID"
	SCHEMA_CONFIG: dict = None      # fieldname -> {alias.sql_column, fieldtype (eval), display (eval), searchable (eval)}

	# ─── Derived Constants (lazily built & cached per subclass) ───────────────

	@classmethod
	def field_to_column(cls):
		"""Return (and cache) the fieldname -> SQL column map for filter resolution."""
		return cls._derived("_field_to_column", lambda: build_field_to_column(cls.SCHEMA_CONFIG, cls.PRIMARY_KEY_COLUMN))

	@classmethod
	def select_clause(cls):
		"""Return (and cache) the aliased SELECT clause for this table."""
		return cls._derived("_select_clause", lambda: build_select_clause(cls.SCHEMA_CONFIG))

	@classmethod
	def search_columns(cls):
		"""Return (and cache) the list of searchable SQL columns."""
		return cls._derived("_search_columns", lambda: build_search_columns(cls.SCHEMA_CONFIG))

	@classmethod
	def primary_key_field(cls):
		"""Return (and cache) the fieldname mapped to the primary key column."""
		return cls._derived("_primary_key_field", lambda: find_primary_key_field(cls.SCHEMA_CONFIG, cls.PRIMARY_KEY_COLUMN))

	@classmethod
	def _derived(cls, attribute_name, builder):
		"""Compute a derived constant once per subclass and cache it in the subclass __dict__.

		The cache is stored on the concrete subclass (not the shared base) so two
		different DocTypes never collide on the same cached value.
		"""
		if attribute_name not in cls.__dict__:
			setattr(cls, attribute_name, builder())
		return cls.__dict__[attribute_name]

	@classmethod
	def _to_document_dict(cls, record):
		"""Convert a raw SQL result row into a frappe._dict suitable for a virtual document.

		Normalizes SQL Server types into Frappe-friendly primitives (notably GUID
		`uniqueidentifier` columns, which pymssql returns as uuid.UUID objects) and
		sets the `name` meta-field from the primary key field. Used by both
		load_from_db and get_list so the two paths stay consistent.
		"""
		record = normalize_record(record)
		return frappe._dict({**record, "name": record[cls.primary_key_field()]})

	# ─── Read Operations ──────────────────────────────────────────────────────

	@classmethod
	def load_from_db(self):
		"""Load a single record from SQL Server by primary key and populate this document."""
		query = f'SELECT {self.select_clause()} FROM {self.TABLE_NAME}'
		if self.JOIN_CLAUSES is not None:
			query += f' {self.JOIN_CLAUSES}'
		query += f' WHERE {self.TABLE_NAME}.ID = %s'

		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			result = ascend.sql(
				query=query,
				values=(self.id) # Field storing primary key.
			)

		if not result:
			raise frappe.DoesNotExistError(f"{self.doctype} '{self.name}' not found.")

		super(Document, self).__init__(self._to_document_dict(result))

	@classmethod
	def get_list(cls, filters=None, page_length=20, start=0, txt=None, or_filters=None, **kwargs):
		"""Fetch a paginated, filtered, sorted list of records.

		Wires the list view's `order_by` through to AscendDatabase (mapping the
		Frappe fieldname to its SQL column) so column-header sorting works. Returns
		a list of frappe._dict rows, each with `name` set to the primary key value.
		"""
		order_column, order_direction = cls._resolve_order_by(kwargs.get("order_by"))

		if order_column is None: # Order by id_column by default
			order_by = cls.primary_key_field()

		where_clause, values = _build_where_clause(
			cls.field_to_column(), filters, cls.search_columns(), txt, or_filters
		)
		query = (
			f"SELECT {cls.select_clause()} FROM {cls.TABLE_NAME}"
			f"{where_clause}"
			f" ORDER BY {order_by} {order_direction} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
		)
		values += [start or 0, page_length or 20]

		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			results = ascend.sql(
				query=query,
				values=values,
				as_dict=True
			)

		return [cls._to_document_dict(record) for record in results]
	
	@classmethod
	def get_count(cls, filters=None, txt=None, or_filters=None, **_):
		"""Return the number of records matching the current filters or search text."""
		
		where_clause, values = _build_where_clause(
			cls.field_to_column, filters, cls.search_columns, txt, or_filters
		)
		query = f"SELECT COUNT(*) FROM {cls.TABLE_NAME}{where_clause}"
		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			result = ascend.sql(query=query, values=values)

		return result[0][0] if result else 0
	
	@staticmethod
	def get_stats(**_):
		"""No sidebar stats for Ascend virtual DocTypes."""
		pass
			 
	# ─── Order-By Resolution ──────────────────────────────────────────────────

	# Trailing sort direction on an order_by clause, e.g. " asc" / " DESC".
	_ORDER_DIRECTION_PATTERN = re.compile(r"\s+(asc|desc)\s*$", re.IGNORECASE)
	# Backtick-quoted identifier segments, e.g. `tabAscend Product` and `description`.
	_BACKTICK_SEGMENT_PATTERN = re.compile(r"`([^`]+)`")

	@classmethod
	def _resolve_order_by(cls, order_by):
		"""Translate a Frappe order_by string into an (sql_column, direction) pair.

		Frappe sends order clauses like `` `tabAscend Product`.`description` asc ``.
		Only the first clause is honored. The fieldname is mapped to its SQL column;
		if it has no mapping (e.g. the default `creation`, which no Ascend table
		has), returns (None, "ASC") so AscendDatabase falls back to ordering by the
		primary key. Direction is constrained to ASC/DESC.

		Parsing is backtick-aware rather than whitespace-split: the `tab<DocType>`
		prefix can itself contain spaces (e.g. "Ascend Product"), which would break
		a naive split.
		"""
		if not order_by:
			return None, "ASC"

		first_clause = order_by.split(",")[0].strip()
		if not first_clause:
			return None, "ASC"

		direction = "ASC"
		direction_match = cls._ORDER_DIRECTION_PATTERN.search(first_clause)
		if direction_match:
			direction = direction_match.group(1).upper()
			first_clause = first_clause[: direction_match.start()].strip()

		# The fieldname is the last backtick-quoted segment (`tabX`.`field`), or, for
		# an unquoted clause, the identifier after the final dot.
		backtick_segments = cls._BACKTICK_SEGMENT_PATTERN.findall(first_clause)
		fieldname = backtick_segments[-1] if backtick_segments else first_clause.split(".")[-1].strip()

		sql_column = cls.field_to_column().get(fieldname)
		return sql_column, direction
		  
	
	# ─── Read-Only Guards ─────────────────────────────────────────────────────
	
	'''The following methods are required for Virtual Doctypes, however they are not implemented in order to maintain
	the read-only nature of the Ascend Virtual Doctypes.'''

	def db_insert(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def db_update(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def delete(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")