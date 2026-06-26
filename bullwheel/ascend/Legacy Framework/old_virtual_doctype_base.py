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
	normalize_record,
)
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database

# ─── Static Helper Functions ───────────────────────────────────────

def _build_join_clause(join_config):
	"""Build a SQL JOIN string from a JOIN_CONFIG list.

	Each entry in `join_config` describes one JOIN clause:
	    {"join": "LEFT JOIN", "table": "Categories", "alias": "cat", "on": "Products.TopicID = cat.ID"}

	`alias` is optional. Returns an empty string when `join_config` is None or empty.
	All entries are concatenated with a single space separator.
	"""
	if not join_config:
		return ""
	parts = []
	for join_entry in join_config:
		join_type = join_entry.get("join", "JOIN")
		table = join_entry["table"]
		alias = join_entry.get("alias", "")
		on_condition = join_entry["on"]
		part = f"{join_type} {table}"
		if alias:
			part += f" AS {alias}"
		part += f" ON {on_condition}"
		parts.append(part)
	return " ".join(parts)

def _clean_field_parameter(field):
	"""Removes assumed table name and formating from field names.
	For example, the parameter '`tabVendor`.`name`' should be resolved to just 'name'."""
	return field.split('.')[-1].replace('`','')

def _extract_search_text(txt, or_filters):
		"""Return the raw search string from either a direct txt arg or Frappe's or_filters list."""
		if txt:
			return txt
		if or_filters:
			for filter_condition in or_filters:
				if len(filter_condition) >= 4 and filter_condition[2].lower() == "like":
					return filter_condition[3].strip("%")
		return None

# Maps the human-readable filter types accepted in dict-format filters (and the
# symbolic operators Frappe sends in list-format filters) to SQL operators.
_FILTER_TYPE_TO_SQL_OPERATOR = {
	"equals": "=",
	"not equals": "!=",
	"like": "LIKE",
	"not like": "NOT LIKE",
	"in": "IN",
	"not in": "NOT IN",
	"is": "IS",
	# Symbolic operators carried through from Frappe's list-format filters.
	"=": "=",
	"!=": "!=",
	"<": "<",
	"<=": "<=",
	">": ">",
	">=": ">=",
}

# Maps an "Is" filter's text to the SQL null-test it produces. The null keyword
# is part of the SQL syntax (not a bindable value), so it is emitted literally.
_IS_TEXT_TO_NULL_CLAUSE = {
	"set": "NOT NULL",
	"not set": "NULL",
	"null": "NULL",
	"not null": "NOT NULL",
}

def _iter_filters(filters):
	"""Yield (fieldname, filter_type, text) tuples from any supported filter format.

	Accepts three shapes:
	  * named-type dict   — {fieldname: [type, text]}, e.g. {"brand": ["Like", "Rossi%"]}
	  * plain dict        — {fieldname: value}, treated as an Equals filter
	  * Frappe list format — [[doctype, fieldname, operator, value]]

	A dict value is read as a [type, text] pair only when it is a two-element
	list/tuple whose first element is a recognized filter type; otherwise the
	whole value is treated as the text of an Equals filter (so a literal
	two-element value is not misread as a type/text pair). Yields nothing when
	`filters` is falsy.
	"""
	if not filters:
		return

	if isinstance(filters, dict):
		for fieldname, raw_filter in filters.items():
			if (
				isinstance(raw_filter, (list, tuple))
				and len(raw_filter) == 2
				and isinstance(raw_filter[0], str)
				and raw_filter[0].strip().lower() in _FILTER_TYPE_TO_SQL_OPERATOR
			):
				yield fieldname, raw_filter[0], raw_filter[1]
			else:
				yield fieldname, "Equals", raw_filter
	else:
		for filter_item in filters:
			yield filter_item[1], filter_item[2], filter_item[3]

def _build_filter_condition(column, filter_type, text):
	"""Build one parameterized SQL condition and its bound values for a single filter.

	`filter_type` is case-insensitive and may be a human-readable name (Equals,
	Not Equals, Like, Not Like, In, Not In, Is) or a symbolic operator. For Like /
	Not Like the caller supplies `%` wildcards directly in `text`. In / Not In
	expect `text` to be a list/tuple of values. Is expects "set" / "not set"
	(equivalently "null" / "not null") and produces an IS [NOT] NULL test with no
	bound value. Returns (condition_string, values) where `values` is the list of
	parameters to bind. Raises ValueError for an unrecognized type or Is text.
	"""
	sql_operator = _FILTER_TYPE_TO_SQL_OPERATOR.get(filter_type.strip().lower())
	if sql_operator is None:
		raise ValueError(f"Unsupported filter type: {filter_type!r}")

	if sql_operator in ("IN", "NOT IN"):
		values = list(text)
		placeholders = ", ".join(["%s"] * len(values))
		return f"{column} {sql_operator} ({placeholders})", values

	if sql_operator == "IS":
		null_clause = _IS_TEXT_TO_NULL_CLAUSE.get(str(text).strip().lower())
		if null_clause is None:
			raise ValueError(f"Unsupported 'Is' filter text: {text!r} (expected 'set' or 'not set')")
		return f"{column} IS {null_clause}", []

	return f"{column} {sql_operator} %s", [text]

def _build_where_clause(field_to_column, filters, search_columns, txt, or_filters):
	"""Build a parameterized SQL WHERE clause from Frappe filters and search text.

	`filters` may be a named-type dict ({fieldname: [type, text]}), a plain dict
	({fieldname: value}, treated as Equals), or Frappe's list format
	([[doctype, fieldname, operator, value]]). Supported filter types are Equals,
	Not Equals, Like, Not Like, In, Not In, and Is (plus the symbolic comparison
	operators =, !=, <, <=, >, >=). For Like / Not Like, `%` wildcards are taken
	verbatim from the filter text. Fieldnames are resolved to SQL columns via
	`field_to_column`; unrecognized fieldnames are skipped.

	When search text is present (from `txt` or `or_filters`), appends an OR LIKE
	condition across all `search_columns`.
	"""
	conditions = []
	values = []

	for fieldname, filter_type, text in _iter_filters(filters):
		column = field_to_column.get(fieldname)
		if not column:
			continue
		condition, condition_values = _build_filter_condition(column, filter_type, text)
		conditions.append(condition)
		values.extend(condition_values)

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
	TABLE_NAME: str = None        # Ascend SQL table name, e.g. "Products"
	JOIN_CONFIG: list = None      # List of JOIN descriptors — see _build_join_clause for the dict shape
	SCHEMA_CONFIG: dict = None    # fieldname -> {sql_column, fieldtype, display, searchable}
	                               # Must include a "name" entry whose sql_column is the primary key.

	# ─── Derived Constants (lazily built & cached per subclass) ───────────────

	@classmethod
	def field_to_column(cls):
		"""Return (and cache) the fieldname -> SQL column map for filter resolution."""
		return cls._derived("_field_to_column", lambda: build_field_to_column(cls.SCHEMA_CONFIG))

	@classmethod
	def select_clause(cls):
		"""Return (and cache) the aliased SELECT clause for this table."""
		return cls._derived("_select_clause", lambda: build_select_clause(cls.SCHEMA_CONFIG))

	@classmethod
	def search_columns(cls):
		"""Return (and cache) the list of searchable SQL columns."""
		return cls._derived("_search_columns", lambda: build_search_columns(cls.SCHEMA_CONFIG))

	@classmethod
	def join_clause(cls):
		"""Return (and cache) the SQL JOIN string built from JOIN_CONFIG.

		Returns an empty string when JOIN_CONFIG is None, so callers can safely
		check truthiness or concatenate without special-casing the no-join case.
		"""
		return cls._derived("_join_clause", lambda: _build_join_clause(cls.JOIN_CONFIG))

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
		`uniqueidentifier` columns, which pymssql returns as uuid.UUID objects). The
		`name` meta-field comes through the SELECT alias directly from the `name` entry
		in SCHEMA_CONFIG — no special-casing required.
		"""
		return frappe._dict(normalize_record(record))

	# ─── Read Operations ──────────────────────────────────────────────────────

	def load_from_db(self):
		"""Load a single record from SQL Server by primary key and populate this document."""
		join = self.join_clause()
		name_column = self.SCHEMA_CONFIG["name"]["sql_column"]
		query = f"SELECT {self.select_clause()} FROM {self.TABLE_NAME}"
		if join:
			query += f" {join}"
		query += f" WHERE {name_column} = %s"

		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			result = ascend.sql(
				query=query,
				values=(self.name,),
				as_dict=True
			)

		if not result:
			raise frappe.DoesNotExistError(f"{self.doctype} '{self.name}' not found.")

		super(Document, self).__init__(self._to_document_dict(result[0]))

	@classmethod
	def get_link_field_values(cls, name, fieldnames):
		"""Fetch only the requested fields for one record by primary key.

		An optimized alternative to load_from_db for callers (e.g. Link-field title display)
		that need a couple of columns rather than the whole document. Each fieldname is
		aliased to itself; fieldnames with no SQL column (NULL placeholders or unknown
		names) come back as None. Returns a dict keyed by fieldname, or None when no record
		matches. The `name` field maps to the primary key column via field_to_column, so it
		can be requested like any other field and is UUID-normalized in the result.
		"""
		field_to_column = cls.field_to_column()
		select_expressions = ", ".join(
			f"{field_to_column.get(fieldname) or 'NULL'} AS {fieldname}" for fieldname in fieldnames
		)
		join = cls.join_clause()
		name_column = cls.SCHEMA_CONFIG["name"]["sql_column"]
		query = f"SELECT {select_expressions} FROM {cls.TABLE_NAME}"
		if join:
			query += f" {join}"
		query += f" WHERE {name_column} = %s"

		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			result = ascend.sql(query=query, values=(name,), as_dict=True)

		if not result:
			return None

		return normalize_record(result[0])

	@classmethod
	#@frappe.validate_and_sanitize_search_inputs
	def get_list(cls, fields=None, filters=None, page_length=20, start=0, txt=None, or_filters=None, as_list=False,**kwargs):
		"""Fetch a paginated, filtered, sorted list of records.

		Wires the list view's `order_by` through to AscendDatabase (mapping the
		Frappe fieldname to its SQL column) so column-header sorting works. Returns
		a list of frappe._dict rows, each with `name` set to the primary key value.
		"""
		order_by, order_direction = cls._resolve_order_by(kwargs.get("order_by"))

		if fields is None:
			select_clause = cls.select_clause()
		else:
			select_expressions = []
			for field in fields:
				if type(field) != str: # There was some weird dict passed as a paramater. I don't know it's purpose. This skips over it.
					continue
				field = _clean_field_parameter(field)
				if field not in cls.SCHEMA_CONFIG.keys(): # Skip fields like "owner"
					continue
				sql_column = cls.SCHEMA_CONFIG.get(field).get("sql_column") or "NULL"
				select_expressions.append(f"{sql_column} AS {field}")
			select_clause = ", ".join(select_expressions)
				

		if order_by is None:
			order_by = cls.SCHEMA_CONFIG["name"]["sql_column"]

		join = cls.join_clause()
		where_clause, values = _build_where_clause(
			cls.field_to_column(), filters, cls.search_columns(), txt, or_filters
		)
		query = (
			f"SELECT {select_clause} FROM {cls.TABLE_NAME}"
			f"{' ' + join if join else ''}"
			f"{where_clause}"
			f" ORDER BY {order_by} {order_direction} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
		)
		values += [start or 0, page_length or 20]

		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			results = ascend.sql(
				query=query,
				values=values
			)

		if as_list:
			return [tuple(row_dict.values()) for row_dict in results]

		return [cls._to_document_dict(record) for record in results]
	
	@classmethod
	def get_count(cls, filters=None, txt=None, or_filters=None, **_):
		"""Return the number of records matching the current filters or search text."""
		join = cls.join_clause()
		where_clause, values = _build_where_clause(
			cls.field_to_column(), filters, cls.search_columns(), txt, or_filters
		)
		query = (
			f"SELECT COUNT(*) FROM {cls.TABLE_NAME}"
			f"{' ' + join if join else ''}"
			f"{where_clause}"
		)
		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			result = ascend.sql(
				query=query, 
				values=values,
				as_list=True
			)

		return result[0][0] if result else 0
	
	@staticmethod
	def get_stats(**_):
		"""No sidebar stats for Ascend virtual DocTypes."""
		pass

	# ─── Search Function Hook ─────────────────────────────────────────────

	@classmethod
	def make_search_function(cls, display_fields):
		"""Build a whitelisted Link-field search hook for this DocType.

		Bind the result to a module-level name in the controller and register that
		dotted path under `standard_queries` in hooks.py. `display_fields` are the
		fieldnames shown after the id in each autocomplete tuple. The returned
		function matches Frappe's `standard_queries` contract and queries Ascend
		directly, bypassing the search_widget pipeline. Returns
		`(name, *display_field_values)` tuples for autocomplete, or `frappe._dict`
		rows (with `name` populated) when called with `as_dict=True`.
		"""
		table_name = cls.TABLE_NAME
		name_column = cls.SCHEMA_CONFIG["name"]["sql_column"]
		select_clause = cls.select_clause()
		field_to_column = cls.field_to_column()
		search_columns = cls.search_columns()
		join = cls.join_clause()

		@frappe.whitelist()
		@frappe.validate_and_sanitize_search_inputs
		def virtual_doctype_search(doctype, txt, searchfield, start, page_len, _filters, as_dict=False):
			# doctype, searchfield, filters are required positional args from the
			# standard_queries contract but are not needed for the Ascend query.
			_ = doctype, searchfield

			where_clause, values = _build_where_clause(field_to_column, _filters, search_columns, txt, None)
			query = (
				f"SELECT {select_clause} FROM {table_name}"
				f"{' ' + join if join else ''}"
				f"{where_clause}"
				f" ORDER BY {name_column} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
			)

			values += [int(start), int(page_len)]

			with MSSQLDatabase(get_default_ascend_database()) as ascend:
				records = ascend.sql(query=query, values=values, as_dict=True)

			records = [normalize_record(record) for record in records]

			if as_dict:
				return [frappe._dict(record) for record in records]

			return [
				(record["name"], *(record.get(field) or "" for field in display_fields))
				for record in records
			]

		return virtual_doctype_search

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