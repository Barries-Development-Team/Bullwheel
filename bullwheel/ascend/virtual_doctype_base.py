# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import re
import uuid

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core import get_default_ascend_database, print_console_warning

# ─── Static Helper Functions ───────────────────────────────────────

def has_duplicates(dict_list):
    seen = set()
    for d in dict_list:
        # Sort items to handle differing key orderings for identical data
        dict_tuple = tuple(sorted(d.items()))
        if dict_tuple in seen:
            return True
        seen.add(dict_tuple)
    return False

def to_document_dict(record):
	"""Returns a proper frappe dict with every `uuid.UUID` value converted to its string form"""
	return frappe._dict({
		fieldname: (str(value) if isinstance(value, uuid.UUID) else value)
		for fieldname, value in record.items()
	})

def clean_fieldname(field):
	"""Removes assumed table name and formating from field names.
	For example, the parameter '`tabVendor`.`name`' should be resolved to just 'name'."""
	return field.split('.')[-1].replace('`','')

def parse_parameter(parameter: str) -> list[str]:
	"""Split a string on whitespace, but text inside backtick pairs is treated as a single token."""
	return re.findall(r'(?:`[^`]*`|\S)+', parameter)


# Frappe meta-fields that desk features (tags, assignments, likes, sidebar counts) filter on
# even though virtual DocTypes rarely map them. A filter on one of these is silently skipped
# when unmapped; a filter on any other unmapped field raises. A SCHEMA_CONFIG mapping, when
# present, always takes precedence over this list.
IGNORED_STANDARD_FIELDS = frozenset({
	'_user_tags', '_comments', '_assign', '_liked_by', '_seen',
	'docstatus', 'idx', 'owner', 'modified_by', 'creation', 'modified',
	'parent', 'parentfield', 'parenttype',
})

# Whitelist of filter operators and their SQL renderings. The 'is' operator ("is set" /
# "not set" list-view filters) is handled separately since it renders as IS [NOT] NULL.
OPERATOR_MAP = {
	'=': '=',
	'!=': '!=',
	'<': '<',
	'<=': '<=',
	'>': '>',
	'>=': '>=',
	'like': 'LIKE',
	'not like': 'NOT LIKE',
	'in': 'IN',
	'not in': 'NOT IN',
}


class AbstractVirtualDocType(Document):

	# ─── Subclass Contract — override these ───────────────────────────────────
	TABLE_NAME: str = None       		# Ascend SQL table name, e.g. "Products"
	JOIN_CONFIG: list = None     		# List of JOIN descriptors — see _build_join_clause for the dict shape
	SCHEMA_CONFIG: dict = None    		# Fieldname -> SQL Column. Must include a "name" entry whose sql_column is the primary key.
	NAME_EXPRESSION: str = None    		# Optional raw SQL expression for the primary key. When set, overrides
	                             		# SCHEMA_CONFIG['name'] as the SQL for `name` in SELECT, WHERE, filters, and
	                             		# ORDER BY (and makes the SCHEMA_CONFIG 'name' entry optional).
	SHOW_FIELD_WARNINGS: bool = True	# Display a warning in the console if an expected field has no mapping in SCHEMA_CONFIG
	ALT_NAME_RESOLUTION_FIELDS: list = None	# Optional list of additional SCHEMA_CONFIG fieldnames a record can also be
	                             		# identified by, in addition to 'name' (e.g. ['upc'] lets a Store-SKU-keyed
	                             		# doctype also be looked up by UPC).


	# ─── Helper Methods  ──────────────────────────────────────────────────────

	@classmethod
	def _column_for(cls, field: str) -> str | None:
		"""Resolve a fieldname to the SQL it maps to. The primary key ('name') resolves to
		NAME_EXPRESSION when that attribute is set; every other field (and 'name' when
		NAME_EXPRESSION is unset) resolves straight from SCHEMA_CONFIG."""
		if field == 'name' and cls.NAME_EXPRESSION:
			return cls.NAME_EXPRESSION
		return cls.SCHEMA_CONFIG.get(field)

	@classmethod
	def _required_column_for(cls, field: str) -> str | None:
		"""Resolve a filter fieldname to its SQL column, enforcing the unmapped-field policy:
		Frappe's own meta-fields (tags, assignments, timestamps, ...) are skipped with a console
		warning so stock desk features keep working, while any other unmapped field raises a
		clear error instead of producing invalid SQL."""
		sql_column = cls._column_for(field)
		if sql_column is not None:
			return sql_column
		if field in IGNORED_STANDARD_FIELDS:
			if cls.SHOW_FIELD_WARNINGS:
				print_console_warning(
					f"Ascend Virtual Doc Warning: Ignoring filter on standard field '{field}' — "
					f"no mapping in {cls.__name__}.SCHEMA_CONFIG."
				)
			return None
		frappe.throw(f"Cannot filter {cls.__name__} by '{field}': no SCHEMA_CONFIG mapping exists.")

	@classmethod
	def _normalize_filter_conditions(cls, filters) -> list[tuple]:
		"""Normalize every filter shape Frappe dispatches into uniform (field, operator, value)
		triples. Accepts a dict ({field: value} or {field: (operator, value)}) or a list of
		3-/4-element conditions ([field, operator, value] or [doctype, field, operator, value]).
		Fieldnames are cleaned of backtick/table qualification so SCHEMA_CONFIG lookups always
		see bare fieldnames."""
		if not filters:
			return []

		conditions = []

		if isinstance(filters, dict):
			for field, value in filters.items():
				if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str):
					operator, operand = value
				else:
					operator, operand = '=', value
				conditions.append((clean_fieldname(field), operator, operand))
			return conditions

		for condition in filters:
			if not isinstance(condition, (list, tuple)):
				frappe.throw(f"Unsupported filter condition {condition!r}.")
			if len(condition) == 3:
				field, operator, value = condition
			elif len(condition) == 4:
				_doctype, field, operator, value = condition
			else:
				frappe.throw(f"Unsupported filter condition {condition!r}. Expected 3 or 4 elements.")
			conditions.append((clean_fieldname(field), operator, value))

		return conditions

	@classmethod
	def _build_select_clause(cls, fields: list = [], strict: bool = False) -> str:
		"""Generate an SQL Select clause to fetch the provided fields. If no fields are provided, all are selected.
		The primary key ('name') is always projected — even when NAME_EXPRESSION is set and 'name' is
		omitted from SCHEMA_CONFIG — so load_from_db and list views always receive an identifier.
		Unmapped fields are skipped with a console warning, or raise a ValueError when strict is set;
		either way, resolving zero fields raises rather than emitting invalid SQL."""
		if len(fields) <= 0:
			fields = list(cls.SCHEMA_CONFIG.keys())
			if 'name' not in fields:
				fields.insert(0, 'name')

		select_statements = []
		unmapped_fields = []
		for field in fields:
			sql_column = cls._column_for(field)
			if sql_column is not None:
				select_statements.append(f'{sql_column} AS {field}')
			else:
				unmapped_fields.append(field)

		if unmapped_fields:
			if strict:
				raise ValueError(
					f"{cls.__name__}: no SCHEMA_CONFIG mapping exists for requested field(s) {unmapped_fields}."
				)
			if cls.SHOW_FIELD_WARNINGS:
				for field in unmapped_fields:
					print_console_warning(f"Ascend Virtual Doc Warning: No field mapping exists for {field} in {cls.__name__}.")
				print_console_warning(f"If this is expected, you can disable this warning with SHOW_FIELD_WARNINGS = False.")

		if not select_statements:
			frappe.throw(
				f"None of the requested fields for {cls.__name__} resolve to a SQL column: {fields}."
			)

		return 'SELECT ' + ', '.join(select_statements)

	@classmethod
	def _build_pagination_clause(cls, start: int, page_length: int) -> str:
		"""Build an OFFSET/FETCH pagination clause for SQL Server. Must follow an ORDER BY clause in the query.
		For example, start=20 and page_length=80 skips the first 20 rows and returns the next 80."""
		return f'OFFSET {start} ROWS FETCH NEXT {page_length} ROWS ONLY'
	
	@classmethod
	def _build_join_clause(cls) -> str:
		"""Build a JOIN clause from JOIN_CONFIG. The alias key is optional; when absent, no AS clause is emitted."""
		join_statements = []
		for config in cls.JOIN_CONFIG:
			alias = config.get('alias')
			alias_clause = f' AS {alias}' if alias else ''
			join_statements.append(f'{config.get("join")} {config.get("table")}{alias_clause} ON {config.get("on")}')
		return ' '.join(join_statements)
	
	@classmethod
	def _format_condition(cls, sql_column: str, operator: str, value, values: list) -> str:
		"""Render one 'column operator value' SQL fragment, appending its bound value to `values`.
		The operator must appear in OPERATOR_MAP; the 'is' operator ("set"/"not set" list-view
		filters) translates to an IS [NOT] NULL check with no bound value."""
		operator_key = str(operator).lower()
		if operator_key == 'is':
			return f'{sql_column} IS NOT NULL' if str(value).lower() == 'set' else f'{sql_column} IS NULL'

		sql_operator = OPERATOR_MAP.get(operator_key)
		if sql_operator is None:
			frappe.throw(f"Unsupported filter operator '{operator}' for {cls.__name__}.")

		values.append(value)
		return f'{sql_column} {sql_operator} %s'

	@classmethod
	def _condition_sql(cls, field: str, operator: str, value, values: list) -> str | None:
		"""Build a single SQL condition fragment for one filter condition, appending its bound
		value(s) to `values`. A condition on 'name' is widened to an OR across 'name' plus every
		field in ALT_NAME_RESOLUTION_FIELDS, so a record can be identified by those fields too.
		Returns None (condition dropped) for unmapped standard Frappe fields; raises for any
		other unmapped field."""
		sql_column = cls._required_column_for(field)
		if sql_column is None:
			return None

		if field == 'name' and cls.ALT_NAME_RESOLUTION_FIELDS:
			sub_conditions = []
			for alt_field in ('name', *cls.ALT_NAME_RESOLUTION_FIELDS):
				sub_conditions.append(cls._format_condition(cls._column_for(alt_field), operator, value, values))
			return '(' + ' OR '.join(sub_conditions) + ')'

		return cls._format_condition(sql_column, operator, value, values)

	@classmethod
	def _build_where_clause(cls, values: list, filters=None, or_filters=None) -> str:
		"""Build the WHERE clause from Frappe filters (list or dict format). Filter values are
		appended to the passed values list. Conditions on 'name' are automatically widened per
		ALT_NAME_RESOLUTION_FIELDS; conditions on unmapped standard Frappe fields are dropped."""
		where_statements = []

		and_statements = [
			statement for field, operator, value in cls._normalize_filter_conditions(filters)
			if (statement := cls._condition_sql(field, operator, value, values)) is not None
		]
		if and_statements:
			where_statements.append('(' + ' AND '.join(and_statements) + ')')

		or_statements = [
			statement for field, operator, value in cls._normalize_filter_conditions(or_filters)
			if (statement := cls._condition_sql(field, operator, value, values)) is not None
		]
		if or_statements:
			where_statements.append('(' + ' OR '.join(or_statements) + ')')

		if not where_statements:
			return 'WHERE 1=1'

		return 'WHERE ' + ' AND '.join(where_statements)
	
	@classmethod
	def _build_order_by_clause(cls, order_by: str) -> str:
		"""Build an ORDER BY clause from a Frappe order_by string. Handles both plain field names
		('description asc') and Frappe's fully-qualified backtick form ('`tabX`.`description` asc').
		Fields with no SCHEMA_CONFIG mapping fall back to (SELECT NULL)."""
		parameters = order_by.split(', ')
		order_by_statements = []

		for parameter in parameters:
			tokens = parse_parameter(parameter)
			if not tokens:
				continue
			field = clean_fieldname(tokens[0])
			# The direction token comes from the client, so anything but ASC/DESC is discarded
			# rather than interpolated into the query.
			order = tokens[1].upper() if len(tokens) > 1 else 'ASC'
			if order not in ('ASC', 'DESC'):
				order = 'ASC'
			sql_column = cls._column_for(field)
			if sql_column is not None:
				order_by_statements.append(f'{field} {order}')
			else:
				order_by_statements.append('(SELECT NULL)')

		if len(order_by_statements) <= 0:
			return None

		return 'ORDER BY ' + ', '.join(order_by_statements)
	
	@classmethod
	def _validate_and_clean_fields(cls, fields) -> None:
		"""Reformat incorrectly assumed table names from fields list. E.g. '`tabAscend Product`.`name`' to 'name'.
		Removes improper field argument types (e.i. not a string). Field argument is edited directly.
		Unmapped-field reporting is owned by _build_select_clause and the WHERE-clause policy."""
		valid_fields = []
		for field in fields:
			if not isinstance(field, str):
				print_console_warning(f"Ascend Virtual Doc Warning: Invalid field parameter {field}.")
				continue
			valid_fields.append(clean_fieldname(field))
		fields[:] = valid_fields  # In-place replacement so the caller's list is updated.

	
	# ─── Read Operations ──────────────────────────────────────────────────────


	def load_from_db(self) -> None:
		"""Load this document by primary key. When ALT_NAME_RESOLUTION_FIELDS is set, self.name is
		also matched against those additional columns (e.g. UPC as well as Store SKU for Ascend
		Product), so a Link field can be populated with either identifier."""
		query_clauses = []
		values = []

		query_clauses.append(self._build_select_clause())
		query_clauses.append(f'FROM {self.TABLE_NAME}')
		if self.JOIN_CONFIG is not None:
			query_clauses.append(self._build_join_clause())
		query_clauses.append(self._build_where_clause(values=values, filters=[(None, 'name', '=', self.name)]))

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(query=' '.join(query_clauses), values=values, as_dict=True)

		if not records:
			raise frappe.DoesNotExistError(f"{self.doctype} '{self.name}' not found.")

		super(Document, self).__init__(to_document_dict(records[0]))
	
	@classmethod
	def get_values(cls, name, fields: list) -> frappe._dict | None:
		"""Fetch a subset of mapped fields for a single record by primary key, in one query.
		Column names are resolved from SCHEMA_CONFIG so they stay single-sourced. Returns a
		frappe dict of the requested fields, or None when no matching record exists.

		Intended for cheap cross-references (e.g. a child table's virtual fields mirroring a
		few columns of the linked record) where loading the full document is unnecessary.
		The field list is developer-authored, so it is strict: an unmapped or empty request
		raises a ValueError instead of being silently narrowed."""
		if not isinstance(fields, (list, tuple)) or len(fields) == 0:
			raise ValueError(f"{cls.__name__}.get_values requires a non-empty list of fieldnames, got {fields!r}.")

		query_clauses = []
		values=[]
		# SELECT
		query_clauses.append(cls._build_select_clause(list(fields), strict=True))
		# FROM
		query_clauses.append(f'FROM {cls.TABLE_NAME}')
		# JOIN
		if cls.JOIN_CONFIG is not None:
			query_clauses.append(cls._build_join_clause())
		# WHERE
		query_clauses.append(cls._build_where_clause(values=values, filters=[(None, 'name', '=', name)]))

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=values,
				as_dict=True
			)

		return to_document_dict(records[0]) if records else None

	@classmethod
	def _search_values_for_name_condition(cls, filters, or_filters) -> set | None:
		"""Collect every value used in a condition on 'name' across `filters`/`or_filters`. Returns
		None when there is no such condition, so callers can skip the echo-back step entirely."""
		values = set()
		conditions = [*cls._normalize_filter_conditions(filters), *cls._normalize_filter_conditions(or_filters)]
		for field, operator, value in conditions:
			if field != 'name':
				continue
			if str(operator).lower() == 'in':
				values.update(str(v) for v in value)
			else:
				values.add(str(value))
		return values or None

	@classmethod
	def _echo_matched_identifier(cls, records: list, search_values: set) -> list:
		"""Rewrite each record's 'name' to whichever of (name, *ALT_NAME_RESOLUTION_FIELDS) actually
		equals one of the searched values, instead of always the canonical primary key. Frappe's
		batched Link-existence check (Column.validate_values) compares returned names against the
		raw input strings via set membership, so a record found only via an alt field (e.g. UPC)
		must echo that value back as 'name' or it is reported as missing even though a match was
		found."""
		candidate_fields = ['name', *cls.ALT_NAME_RESOLUTION_FIELDS]
		echoed = []
		for record in records:
			record = dict(record)
			record['name'] = next(
				(record[field] for field in candidate_fields if str(record.get(field)) in search_values),
				record.get('name'),
			)
			echoed.append(record)
		return echoed

	@classmethod
	def get_list(cls, doctype: str, fields: list, filters: list, start: int, page_length: int, with_comment_count: str, save_user_settings: bool, or_filters: list = [], as_list: bool = False, group_by: str = None, order_by: str = None, strict = None, **args):

		# Frappe's link search (search_widget) appends a computed `_relevance` column to the
		# fields list and then strips the trailing column positionally from each returned row.
		# We drop that non-string field below (we can't map it), so track how many were removed
		# to re-pad the as_list rows and keep the caller's column alignment — otherwise the
		# strip would eat a real column (e.g. the description subtitle shown under each option).
		original_field_count = len(fields)
		cls._validate_and_clean_fields(fields)
		removed_field_count = original_field_count - len(fields)

		search_values = cls._search_values_for_name_condition(filters, or_filters) if cls.ALT_NAME_RESOLUTION_FIELDS else None
		select_fields = fields
		if search_values:
			select_fields = list(dict.fromkeys([*fields, 'name', *cls.ALT_NAME_RESOLUTION_FIELDS]))

		query_clauses = []
		values = []

		# SELECT
		query_clauses.append(cls._build_select_clause(select_fields))
		# FROM
		query_clauses.append(f'FROM {cls.TABLE_NAME}')
		# JOIN
		if cls.JOIN_CONFIG is not None:
			query_clauses.append(cls._build_join_clause())
		# WHERE
		if filters or or_filters:
			query_clauses.append(cls._build_where_clause(values=values, filters=filters, or_filters=or_filters))
		# ORDER BY (required before OFFSET/FETCH)
		query_clauses.append(cls._build_order_by_clause(order_by) if order_by else 'ORDER BY (SELECT NULL)')
		# OFFSET/FETCH
		query_clauses.append(cls._build_pagination_clause(start, page_length))

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=values,
				as_dict=True
			)

		# Check for duplicate records resulting from bad JOIN configs.
		if has_duplicates(records):
			print_console_warning(f"Ascend Virtual Doc Warning: Duplicate results found in {doctype} query. JOIN_CONFIG for {doctype} may be incorrect.")

		if search_values:
			records = cls._echo_matched_identifier(records, search_values)
			if select_fields != fields:
				records = [{field: record.get(field) for field in fields} for record in records]

		if as_list:
			rows = [[record.get(field) for field in fields] for record in records]
			# Re-pad the columns dropped above (e.g. search's `_relevance`) so callers that
			# strip trailing columns positionally still line up with the real fields.
			if removed_field_count:
				for row in rows:
					row.extend([None] * removed_field_count)
			return rows

		return [to_document_dict(record) for record in records]
	
	@classmethod
	def get_count(cls, doctype: str, filters: list, fields: list, distinct, save_user_settings, strict, or_filters: list = [], limit: int = None, **args):
		query_clauses = []
		values = []

		# SELECT COUNT FROM
		query_clauses.append (f'SELECT COUNT(*) AS count FROM {cls.TABLE_NAME}')
		# JOIN
		if cls.JOIN_CONFIG is not None:
			query_clauses.append(cls._build_join_clause())
		# WHERE
		if filters or or_filters:
			query_clauses.append(cls._build_where_clause(values=values, filters=filters, or_filters=or_filters))

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=values,
				as_dict=True
			)

		return records[0].get('count')
		  	
	# ─── Read-Only Guards ─────────────────────────────────────────────────────
	
	'''The following methods are required for Virtual Doctypes, however they are not implemented in order to maintain
	the read-only nature of the Ascend Virtual Doctypes.'''

	def db_insert(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def db_update(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def delete(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")