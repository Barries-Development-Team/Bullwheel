# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import re
import uuid

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database

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

def bare_column(sql_column: str) -> str:
	"""Extract the bare, lowercase column name from a SQL column reference for comparison.
	Handles table-qualified references ('Products.ID', 'cat.Topic') and bracket-quoted
	names ('[Store UPC]', '[Year]'). 'Products.[Store UPC]' -> 'store upc'."""
	return sql_column.split('.')[-1].strip('[]').lower()


class AbstractVirtualDocType(Document):

	# ─── Subclass Contract — override these ───────────────────────────────────
	TABLE_NAME: str = None       		# Ascend SQL table name, e.g. "Products"
	JOIN_CONFIG: list = None     		# List of JOIN descriptors — see _build_join_clause for the dict shape
	SCHEMA_CONFIG: dict = None    		# Fieldname -> SQL Column. Must include a "name" entry whose sql_column is the primary key.
	NAME_EXPRESSION: str = None    		# Optional raw SQL expression for the primary key. When set, overrides
	                             		# SCHEMA_CONFIG['name'] as the SQL for `name` in SELECT, WHERE, filters, and
	                             		# ORDER BY (and makes the SCHEMA_CONFIG 'name' entry optional).
	SHOW_FIELD_WARNINGS: bool = True	# Display a warning in the console if an expected field has no mapping in SCHEMA_CONFIG


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
	def _known_table_qualifiers(cls) -> set:
		"""Table names and aliases a qualified column reference may legally use: the primary
		TABLE_NAME plus every table/alias declared in JOIN_CONFIG."""
		qualifiers = {cls.TABLE_NAME}
		for config in (cls.JOIN_CONFIG or []):
			if config.get('alias'):
				qualifiers.add(config['alias'])
			if config.get('table'):
				qualifiers.add(config['table'])
		return qualifiers

	@classmethod
	def validate_schema_config(cls, discovered_columns=None, additional_discovered_columns=None) -> bool:
		"""Validate this class's SCHEMA_CONFIG for structural correctness.

		Always checks that SCHEMA_CONFIG is not empty, that the primary key is defined
		(either a non-null 'name' entry or a NAME_EXPRESSION), and that all values are
		strings or None. When NAME_EXPRESSION is set, its table/alias qualifiers are
		checked against TABLE_NAME + JOIN_CONFIG so an undeclared join surfaces here
		instead of as an opaque SQL bind error at query time.

		When discovered_columns is provided (an iterable of SQL column names from the primary
		table, e.g. from introspect_table_schema), confirms that unqualified column references
		exist in that set. When additional_discovered_columns is provided (column names from
		joined tables), confirms that table-qualified references (containing '.') resolve to a
		known column. Qualified columns are skipped when additional_discovered_columns is not
		provided. The 'name' entry is skipped from column-existence checks when NAME_EXPRESSION
		is set, since an expression is not a plain column.

		Returns True on success; raises ValueError describing the first problem found.
		"""
		schema_config = cls.SCHEMA_CONFIG
		name_expression = cls.NAME_EXPRESSION

		if not schema_config:
			raise ValueError(f"{cls.__name__}: SCHEMA_CONFIG is empty or None.")

		# The primary key must be defined either as a NAME_EXPRESSION or a non-null 'name' entry.
		if not name_expression and not schema_config.get('name'):
			raise ValueError(
				f"{cls.__name__}: define the primary key via a non-null SCHEMA_CONFIG 'name' entry "
				f"or by setting NAME_EXPRESSION."
			)
		if name_expression is not None and not isinstance(name_expression, str):
			raise ValueError(
				f"{cls.__name__}: NAME_EXPRESSION must be a string SQL expression, got {name_expression!r}."
			)

		for fieldname, sql_column in schema_config.items():
			if sql_column is not None and not isinstance(sql_column, str):
				raise ValueError(
					f"{cls.__name__}: Field '{fieldname}' has an invalid value {sql_column!r}. "
					f"Expected a string SQL column name or None."
				)

		# Guardrail: every table/alias a NAME_EXPRESSION qualifies with must be declared, otherwise the
		# query throws a bind error at runtime. Strip bracket-quoted names and string literals first so
		# their internal dots/text don't register as spurious qualifiers.
		if name_expression:
			scannable = re.sub(r"\[[^\]]*\]|'[^']*'", '', name_expression)
			referenced = set(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*\.', scannable))
			unknown = referenced - cls._known_table_qualifiers()
			if unknown:
				raise ValueError(
					f"{cls.__name__}: NAME_EXPRESSION references undeclared table/alias qualifier(s) "
					f"{sorted(unknown)}. Add them to JOIN_CONFIG or qualify with the primary table "
					f"'{cls.TABLE_NAME}'."
				)

		if discovered_columns is not None or additional_discovered_columns is not None:
			primary_columns = {bare_column(col) for col in discovered_columns} if discovered_columns else None
			joined_columns = {bare_column(col) for col in additional_discovered_columns} if additional_discovered_columns else None

			for fieldname, sql_column in schema_config.items():
				if not sql_column:
					continue
				if fieldname == 'name' and name_expression:
					continue  # An expression-backed primary key is not a plain column.
				is_table_qualified = '.' in sql_column
				bare = bare_column(sql_column)
				if is_table_qualified:
					if joined_columns is not None and bare not in joined_columns:
						raise ValueError(
							f"{cls.__name__}: Field '{fieldname}' maps to joined column '{sql_column}', "
							f"which was not found in the introspected joined-table schema."
						)
				else:
					if primary_columns is not None and bare not in primary_columns:
						raise ValueError(
							f"{cls.__name__}: Field '{fieldname}' maps to SQL column '{sql_column}', "
							f"which was not found in the introspected primary table schema."
						)

		return True

	@classmethod
	def _build_select_clause(cls, fields: list = []) -> str:
		"""Generate an SQL Select clause to fetch the provided fields. If no fields are provided, all are selected.
		The primary key ('name') is always projected — even when NAME_EXPRESSION is set and 'name' is
		omitted from SCHEMA_CONFIG — so load_from_db and list views always receive an identifier."""
		if len(fields) <= 0:
			fields = list(cls.SCHEMA_CONFIG.keys())
			if 'name' not in fields:
				fields.insert(0, 'name')

		select_statements = []
		for field in fields:
			sql_column = cls._column_for(field)
			if sql_column is not None:
				select_statements.append(f'{sql_column} AS {field}')

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
	def _build_where_clause(cls, filters: list, or_filters: list = [], values: list = []) -> str:
		"""Build the WHERE clause from a list of filters. Filter values are appended to the passed values list."""

		where_statements = []

		# AND Filters: (Condition 1 AND Condition 2 AND ... AND Condition n)
		and_statements = []
		for _, field, operator, value in filters: # Tuple unpacking supports both list-formatted and tuple-formatted filters.
			and_statements.append(f'{cls._column_for(field)} {operator} %s')
			values.append(value) # Appends the value to the list of values passed as an argument.
		if len(and_statements) > 0:
			where_statements.append('(' + ' AND '.join(and_statements) + ')')

		# OR Filters: (Condition 1 OR ... OR Condition n)
		or_statements = []
		for _, field, operator, value in or_filters:
			or_statements.append(f'{cls._column_for(field)} {operator} %s')
			values.append(value)
		if len(or_statements) > 0:
			where_statements.append('(' + ' OR '.join(or_statements) + ')')

		if len(where_statements) <= 0:
			return 'WHERE 1=1' # Equivalent to having no where clause at all.
		
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
			order = tokens[1].upper() if len(tokens) > 1 else 'ASC'
			sql_column = cls._column_for(field)
			if sql_column is not None:
				order_by_statements.append(f'{field} {order}')
			else:
				order_by_statements.append('(SELECT NULL)')

		if len(order_by_statements) <= 0:
			return None

		return 'ORDER BY ' + ', '.join(order_by_statements)
	
	@classmethod
	def _validate_and_clean_fields(cls, fields, doctype) -> None:
		"""Reformat incorrectly assumed table names from fields list. E.g. '`tabAscend Product`.`name`' to 'name'.
		Removes improper field argument types (e.i. not a string). Field argument is edited directly."""
		valid_fields = []
		for field in fields:
			if not isinstance(field, str):
				print(f"\033[33mAscend Virtual Doc Warning: Invalid field parameter {field}.\033[0m")
				continue
			valid_fields.append(clean_fieldname(field))
		fields[:] = valid_fields  # In-place replacement so the caller's list is updated.

		# Display a warning to the console if an expected field has no mapping in the schema config.
		if cls.SHOW_FIELD_WARNINGS:
			unmapped = [field for field in fields if cls.SCHEMA_CONFIG.get(field) is None]
			if unmapped:
				for field in unmapped:
					print(f"\033[33mAscend Virtual Doc Warning: No field mapping exists for {field} in {doctype}.\033[0m")
				print(f"\033[33mIf this is expected, you can disable this warning with SHOW_FIELD_WARNINGS = False.\033[0m")

	
	# ─── Read Operations ──────────────────────────────────────────────────────


	def load_from_db(self):
		query_clauses = []
		# SELECT
		query_clauses.append(self._build_select_clause())
		# FROM
		query_clauses.append(f'FROM {self.TABLE_NAME}')
		# JOIN
		if self.JOIN_CONFIG is not None:
			query_clauses.append(self._build_join_clause())
		# WHERE
		query_clauses.append(f'WHERE {self._column_for('name')} = %s')

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=[self.name],
				as_dict=True
			)

		if not records:
			raise frappe.DoesNotExistError(f"{self.doctype} '{self.name}' not found.")

		super(Document, self).__init__(to_document_dict(records[0]))
	
	@classmethod
	def get_values(cls, name, fields: list) -> frappe._dict | None:
		"""Fetch a subset of mapped fields for a single record by primary key, in one query.
		Column names are resolved from SCHEMA_CONFIG so they stay single-sourced. Returns a
		frappe dict of the requested fields, or None when no matching record exists.

		Intended for cheap cross-references (e.g. a child table's virtual fields mirroring a
		few columns of the linked record) where loading the full document is unnecessary."""
		query_clauses = []
		# SELECT
		query_clauses.append(cls._build_select_clause(fields))
		# FROM
		query_clauses.append(f'FROM {cls.TABLE_NAME}')
		# JOIN
		if cls.JOIN_CONFIG is not None:
			query_clauses.append(cls._build_join_clause())
		# WHERE
		query_clauses.append(f'WHERE {cls._column_for("name")} = %s')

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=[name],
				as_dict=True
			)

		return to_document_dict(records[0]) if records else None

	@classmethod
	def get_list(cls, doctype: str, fields: list, filters: list, start: int, page_length: int, with_comment_count: str, save_user_settings: bool, or_filters: list = [], as_list: bool = False, group_by: str = None, order_by: str = None, strict = None, **args):
		
		cls._validate_and_clean_fields(fields, doctype)

		query_clauses = []
		values = []

		# SELECT
		query_clauses.append(cls._build_select_clause(fields))
		# FROM
		query_clauses.append(f'FROM {cls.TABLE_NAME}')
		# JOIN
		if cls.JOIN_CONFIG is not None:
			query_clauses.append(cls._build_join_clause())
		# WHERE
		if len(filters) > 0 or len(or_filters) > 0:
			query_clauses.append(cls._build_where_clause(filters, or_filters, values)) # Values appended to list.
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
			print(f"\033[33mAscend Virtual Doc Warning: Duplicate results found in {doctype} query. JOIN_CONFIG for {doctype} may be incorrect.\033[0m")

		if as_list:
			return [[record.get(field) for field in fields] for record in records] # Order of fields in returned list enforced by field parameter.

		return [to_document_dict(record) for record in records]
	
	@classmethod
	def get_count(cls, doctype: str, filters: list, fields: list, distinct, limit, save_user_settings, strict, or_filters: list = [], **args):
		query_clauses = []
		values = []

		# SELECT COUNT FROM
		query_clauses.append (f'SELECT COUNT(*) AS count FROM {cls.TABLE_NAME}')
		# JOIN
		if cls.JOIN_CONFIG is not None:
			query_clauses.append(cls._build_join_clause())
		# WHERE
		if len(filters) > 0 or len(or_filters) > 0:
			query_clauses.append(cls._build_where_clause(filters, or_filters, values))

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