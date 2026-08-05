# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import re
import uuid

import frappe
from frappe.model.document import Document
from frappe.model.base_document import get_controller
from frappe.utils import get_datetime, getdate

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core import get_default_ascend_database, print_console_warning, resolve_attributed_ascend_user_id
from bullwheel.bullwheel_core.exceptions import AscendAttributionUserNotConfigured
from bullwheel.ascend.schema_config import normalize_schema_config

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

# Frappe's default 'creation'/'modified' fields have a fixed Datetime fieldtype but, unlike
# custom fields, are not listed in meta.get_field() — so db_update's type normalization can't
# discover their fieldtype from meta and needs this fallback instead.
STANDARD_DATETIME_FIELDS = frozenset({'creation', 'modified'})

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
	ALLOW_WRITE: bool = False			# If true, the Virtual Doctype Framework can edit the Ascend SQL table. Requires INSERT, UPDATE permissions.
	INSERT_DEFAULTS: dict = None 		# Fieldname -> value (or zero-arg callable returning a value, resolved at insert
										# time — use this for anything that must reflect the moment of the insert, e.g. a
										# timestamp) written by db_insert when the document carries no value of its own.
										# For an Ascend column the DocType does not surface as a field at all, the column
										# is simply absent from the INSERT and lands at whatever the table's default is —
										# NULL when there isn't one. Ascend then treats that row as invisible wherever it
										# filters on the column: a NULL Products.ModifierLocationID dropped 220 of 243
										# lines out of an imported purchase order's item grid while the header still
										# counted them. Declare the columns Ascend expects a real value in here. Keys must
										# map to a TABLE_NAME column in SCHEMA_CONFIG; validation rejects anything else on
										# migrate. A callable returning None is treated as "no default available" and
										# skipped, same as never declaring the field.
	JOIN_CONFIG: list = None     		# List of JOIN descriptors — see _build_join_clause for the dict shape
	SCHEMA_CONFIG: dict = None    		# Fieldname -> dict of per-field options. Must include a "name" entry naming the
								 		# primary key column (or set NAME_EXPRESSION instead). Every option is documented
								 		# in schema_config.py, which also owns normalization and the valid key set.
	NAME_EXPRESSION: str = None    		# Optional raw SQL expression for the primary key. When set, overrides
								 		# SCHEMA_CONFIG['name'] as the SQL for `name` in SELECT, WHERE, filters, and
								 		# ORDER BY (and makes the SCHEMA_CONFIG 'name' entry optional). A field config
								 		# cannot hold an expression itself, since column names are always bracket-quoted.
	SHOW_FIELD_WARNINGS: bool = True	# Display a warning in the console if an expected field has no mapping in SCHEMA_CONFIG
	EXCLUDE_NULL_NAME: bool = False	# Frappe's document 'name' must be unique and non-null for every record. Set True
										# when the column 'name'/NAME_EXPRESSION resolves to can itself be NULL (e.g. a
										# business field like EmployeeId that isn't populated for every row) — every query
										# then carries an unconditional '<name column> IS NOT NULL', so a null-named row
										# is excluded everywhere rather than crashing Link search's relevance sort (which
										# assumes 'name' is always a string) or silently colliding as a phantom duplicate.
	MAX_BATCH_INSERT_SIZE: int = 1000	# T-SQL's per-statement row cap for a multi-row INSERT...VALUES — get_bulk_values
										# chunks its temp-table INSERT at this size.
	SHORT_CACHE_TTL_SECONDS: int = 300	# Default TTL for get_bulk_short_cached_values — genuinely mutable Ascend values
										# that are safe to serve slightly stale. Override per-controller if a field needs
										# a different balance of freshness vs. Ascend round trips.

	# Normalized SCHEMA_CONFIGs, keyed by controller class. Deliberately a dict on the base
	# class rather than a plain class attribute: a subclass would otherwise read (and
	# overwrite) the base's value, leaking one controller's config into every other.
	_normalized_schema_configs = {}

	# Memoized cache_fields() results, keyed by controller class, for the same reason.
	_cache_fields_by_class = {}


	# ─── Field Config Accessors  ──────────────────────────────────────────────

	@classmethod
	def _normalized_schema(cls) -> dict:
		"""Return this controller's SCHEMA_CONFIG in its canonical internal form, normalizing
		it once per class. See schema_config.py for the field config contract."""
		normalized = AbstractVirtualDocType._normalized_schema_configs.get(cls)
		if normalized is None:
			normalized = normalize_schema_config(cls)
			AbstractVirtualDocType._normalized_schema_configs[cls] = normalized
		return normalized

	@classmethod
	def _clear_normalized_schema_cache(cls) -> None:
		"""Discard the memoized normalized config and derived cache_fields() list for this
		controller, so a SCHEMA_CONFIG reassigned after the first query (only tests do this) is
		picked up."""
		AbstractVirtualDocType._normalized_schema_configs.pop(cls, None)
		AbstractVirtualDocType._cache_fields_by_class.pop(cls, None)

	@classmethod
	def _field_config(cls, field: str) -> dict | None:
		"""Return the normalized field config for a fieldname, or None when the field has no
		SCHEMA_CONFIG entry."""
		return cls._normalized_schema().get(field)

	@classmethod
	def alternate_name_fields(cls) -> list:
		"""Fieldnames a record can be identified by in addition to 'name', declared with the
		field config's 'alternate_name' flag (e.g. UPC as well as Store SKU for Ascend
		Product). Declaration order is preserved, since _echo_matched_identifier reports the
		first of these fields that matches a searched value."""
		return [
			fieldname for fieldname, field_config in cls._normalized_schema().items()
			if field_config['alternate_name']
		]

	@classmethod
	def linked_id_fields(cls) -> dict:
		"""Maps each editable, JOIN-sourced display field to the writable id field on
		TABLE_NAME holding its foreign key, plus the linked virtual DocType used to resolve
		the display value to that id on save. Declared with the field config's 'linked_id'
		key. See _resolve_linked_id_fields."""
		return {
			fieldname: field_config['linked_id']
			for fieldname, field_config in cls._normalized_schema().items()
			if field_config['linked_id']
		}

	@classmethod
	def cache_fields(cls) -> list:
		"""Fieldnames whose value never changes for a given record (identity columns, creation
		timestamps), declared with the field config's 'cache' flag. get_cached_value checks
		membership in this list on every lookup, so — like _normalized_schema — it is computed
		once per class and memoized rather than rebuilt on every call."""
		fields = AbstractVirtualDocType._cache_fields_by_class.get(cls)
		if fields is None:
			fields = [
				fieldname for fieldname, field_config in cls._normalized_schema().items()
				if field_config['cache']
			]
			AbstractVirtualDocType._cache_fields_by_class[cls] = fields
		return fields


	# ─── Helper Methods  ──────────────────────────────────────────────────────

	@classmethod
	def _column_for(cls, field: str) -> str | None:
		"""Resolve a fieldname to the SQL it maps to — the table-qualified, bracket-quoted
		column reference pre-computed during normalization. The primary key ('name') resolves
		to NAME_EXPRESSION when that attribute is set; every other field (and 'name' when
		NAME_EXPRESSION is unset) resolves straight from SCHEMA_CONFIG."""
		if field == 'name' and cls.NAME_EXPRESSION:
			return cls.NAME_EXPRESSION
		field_config = cls._field_config(field)
		return field_config['sql'] if field_config else None

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
			fields = list(cls._normalized_schema().keys())
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
		alternate-name field, so a record can be identified by those fields too. Returns None
		(condition dropped) for unmapped standard Frappe fields; raises for any other unmapped
		field."""
		sql_column = cls._required_column_for(field)
		if sql_column is None:
			return None

		alternate_name_fields = cls.alternate_name_fields()
		if field == 'name' and alternate_name_fields:
			sub_conditions = []
			for alternate_field in ('name', *alternate_name_fields):
				sub_conditions.append(cls._format_condition(cls._column_for(alternate_field), operator, value, values))
			return '(' + ' OR '.join(sub_conditions) + ')'

		return cls._format_condition(sql_column, operator, value, values)

	@classmethod
	def _column_belongs_to_table(cls, field: str) -> bool:
		"""Returns True when the field's column lives on TABLE_NAME itself rather than on a
		JOIN_CONFIG table. db_insert/db_update can only write columns on TABLE_NAME — joined
		tables are read-only. An unmapped field belongs to no table, so it returns False."""
		field_config = cls._field_config(field)
		if field_config is None or field_config['table'] is None:
			return False
		return field_config['table'].lower() == cls.TABLE_NAME.lower()

	@classmethod
	def _build_where_clause(cls, values: list, filters=None, or_filters=None) -> str:
		"""Build the WHERE clause from Frappe filters (list or dict format). Filter values are
		appended to the passed values list. Conditions on 'name' are automatically widened across
		the alternate-name fields; conditions on unmapped standard Frappe fields are dropped.
		When EXCLUDE_NULL_NAME is set, a '<name column> IS NOT NULL' condition is unconditionally
		ANDed in, so a row whose primary key column is NULL never appears in any result."""
		where_statements = []

		if cls.EXCLUDE_NULL_NAME:
			name_column = cls._column_for('name')
			if name_column is not None:
				where_statements.append(f'{name_column} IS NOT NULL')

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
		"""Load this document by primary key. When alternate-name fields are declared, self.name
		is also matched against those additional columns (e.g. UPC as well as Store SKU for
		Ascend Product), so a Link field can be populated with either identifier."""
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
	def get_bulk_values(cls, names: list, fields: list) -> dict:
		"""Fetch a subset of mapped fields for many records by primary key, in one query — the
		batch counterpart to get_values. Filters via a local SQL Server temp table joined against
		TABLE_NAME rather than a WHERE name IN (...) clause: an IN clause needs one bound
		parameter per name, competing against SQL Server's ~2100-parameters-per-query limit
		alongside the SELECT/JOIN's own parameters, while a temp table's constraint (T-SQL's
		1000-rows-per-multi-row-INSERT limit, chunked via MAX_BATCH_INSERT_SIZE) is independent of
		the lookup query's own parameter count. Local (#-prefixed) temp tables live in tempdb,
		which grants CREATE TABLE to the public role by default, so this needs no permission
		beyond what the login already has for ordinary SELECT/INSERT work.

		Filters/joins on _column_for('name') rather than assuming a raw column, so this also works
		for a NAME_EXPRESSION-backed primary key (e.g. VendorProduct's computed CONCAT(...)).
		Returns a dict keyed by name; a name with no matching Ascend record is simply absent, not a
		None entry — mirrors get_values' single-record contract. The field list is
		developer-authored, so it is strict: an unmapped or empty request raises a ValueError."""
		if not isinstance(fields, (list, tuple)) or len(fields) == 0:
			raise ValueError(f"{cls.__name__}.get_bulk_values requires a non-empty list of fieldnames, got {fields!r}.")

		name_column = cls._column_for('name')
		if name_column is None:
			raise ValueError(f"{cls.__name__}: 'name' has no SQL mapping; get_bulk_values cannot filter by name.")

		unique_names = list(dict.fromkeys(str(name) for name in names if name))
		if not unique_names:
			return {}

		select_clause = cls._build_select_clause(list(dict.fromkeys(['name', *fields])), strict=True)
		results = {}

		with MSSQLDatabase(get_default_ascend_database()) as db:
			db.sql(query="CREATE TABLE #lookup_names (lookup_name NVARCHAR(MAX) NOT NULL)", as_dict=False)

			for start in range(0, len(unique_names), cls.MAX_BATCH_INSERT_SIZE):
				chunk = unique_names[start:start + cls.MAX_BATCH_INSERT_SIZE]
				placeholders = ', '.join(['(%s)'] * len(chunk))
				db.sql(
					query=f"INSERT INTO #lookup_names (lookup_name) VALUES {placeholders}",
					values=chunk,
					as_dict=False
				)

			query_clauses = [select_clause, f'FROM {cls.TABLE_NAME}']
			if cls.JOIN_CONFIG is not None:
				query_clauses.append(cls._build_join_clause())
			query_clauses.append(f'INNER JOIN #lookup_names ON {name_column} = #lookup_names.lookup_name')

			records = db.sql(query=' '.join(query_clauses), as_dict=True)

		for raw_record in records:
			record = to_document_dict(raw_record)
			results[record['name']] = frappe._dict({field: record.get(field) for field in fields})

		return results

	@classmethod
	def get_cached_value(cls, name: str, field: str):

		if field not in cls.cache_fields():
			raise ValueError(f'Field "{field}" is not configured as cachable in DocType SCHEMA_CONFIG.')

		key = f'{cls.TABLE_NAME}-{name}-{field}'

		if cached_value := frappe.cache.get_value(key): # Check if cached value exists
			return cached_value

		value = cls.get_values(name=name, fields=[field]).get(field)
		frappe.cache.set_value(key, value)
		return value

	@classmethod
	def _short_cache_key(cls, name: str, field: str) -> str:
		"""Redis key for one short-TTL-cached (name, field) pair. Distinct suffix from
		get_cached_value's key scheme (f'{TABLE_NAME}-{name}-{field}') so an indefinite cache
		entry and a short-TTL entry for the same field can never collide."""
		return f'{cls.TABLE_NAME}-{name}-{field}-ttl'

	@classmethod
	def get_bulk_short_cached_values(cls, names: list, fields: list, ttl: int = None) -> dict:
		"""Batch, short-TTL-cached read of several fields across many records — for fields that
		genuinely can change in Ascend (no cache_fields() gate; any SCHEMA_CONFIG-mapped field is
		eligible). Checks Redis for every (name, field) pair across all `names` in one pass,
		fetches every requested field for the whole miss set with one get_bulk_values call, and
		repopulates Redis for each resolved value with expires_in_sec=ttl (cls.SHORT_CACHE_TTL_SECONDS
		by default). Returns a dict keyed by name; a name with no cache hit and no Ascend match is
		absent from the result — a negative lookup is never cached, so a record created moments ago
		is never masked by a stale "not found"."""
		ttl = cls.SHORT_CACHE_TTL_SECONDS if ttl is None else ttl
		unique_names = list(dict.fromkeys(str(name) for name in names if name))
		if not unique_names:
			return {}

		values_by_name, names_needing_fetch = {}, []
		for name in unique_names:
			row_values = {}
			for field in fields:
				cached = frappe.cache.get_value(cls._short_cache_key(name, field), expires=True)
				if cached is not None:
					row_values[field] = cached
			values_by_name[name] = row_values
			if len(row_values) < len(fields):
				names_needing_fetch.append(name)

		if names_needing_fetch:
			fresh_records = cls.get_bulk_values(names_needing_fetch, fields)
			for name, fresh in fresh_records.items():
				for field in fields:
					resolved = fresh.get(field)
					frappe.cache.set_value(cls._short_cache_key(name, field), resolved, expires_in_sec=ttl)
					values_by_name[name][field] = resolved

		return {name: frappe._dict(row) for name, row in values_by_name.items() if row}

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
		"""Rewrite each record's 'name' to whichever of (name, *alternate name fields) actually
		equals one of the searched values, instead of always the canonical primary key. Frappe's
		batched Link-existence check (Column.validate_values) compares returned names against the
		raw input strings via set membership, so a record found only via an alternate field (e.g.
		UPC) must echo that value back as 'name' or it is reported as missing even though a match
		was found."""
		candidate_fields = ['name', *cls.alternate_name_fields()]
		echoed = []
		for record in records:
			record = dict(record)
			record['name'] = next(
				(
					record[field]
					for field in candidate_fields
					if (value := str(record.get(field))) in search_values or value.lower() in search_values # Search values may sometimes be normalized to all lower-case.
				),
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

		alternate_name_fields = cls.alternate_name_fields()
		search_values = cls._search_values_for_name_condition(filters, or_filters) if alternate_name_fields else None
		select_fields = fields
		if search_values:
			select_fields = list(dict.fromkeys([*fields, 'name', *alternate_name_fields]))

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
		if filters or or_filters or cls.EXCLUDE_NULL_NAME:
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
		if filters or or_filters or cls.EXCLUDE_NULL_NAME:
			query_clauses.append(cls._build_where_clause(values=values, filters=filters, or_filters=or_filters))

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=values,
				as_dict=True
			)

		return records[0].get('count')
		  	
	# ─── Write Methods ─────────────────────────────────────────────────────
	

	@classmethod
	def _record_exists(cls, name) -> bool:
		"""True when a record already matches `name` (or any alternate-name field, via the
		same widening _build_where_clause already applies to name filters). Guards db_insert
		against silently duplicating a record, since Frappe's virtual-doctype insert flow performs
		no uniqueness check of its own before calling db_insert."""
		return cls.get_count(
			doctype=cls.__name__, filters=[(None, 'name', '=', name)], fields=[],
			distinct=False, save_user_settings=False, strict=None,
		) > 0

	def _normalize_write_value(self, field: str, value):
		"""Converts a document field's value to a type pymssql can bind correctly. Frappe
		stores Datetime/Date field values as plain strings (e.g. '2026-07-17 12:36:35.321314'
		for 'modified'), but pymssql needs a native datetime.datetime/datetime.date object to
		encode the parameter as a SQL Server datetime type — sent as a string, SQL Server must
		implicitly convert it and can reject the microsecond-precision format Frappe produces."""
		if not isinstance(value, str):
			return value

		meta_field = self.meta.get_field(field)
		fieldtype = meta_field.fieldtype if meta_field else None
		if fieldtype is None and field in STANDARD_DATETIME_FIELDS:
			fieldtype = 'Datetime'

		if fieldtype == 'Datetime':
			return get_datetime(value)
		if fieldtype == 'Date':
			return getdate(value)
		return value

	def _collect_writable_fields(self, *, include_name: bool, field_overrides: dict | None = None) -> list[tuple[str, object]]:
		"""Resolve this document's writable (sql_column, value) pairs against SCHEMA_CONFIG,
		shared by db_insert and db_update. A field is writable when it has a SCHEMA_CONFIG
		mapping, that mapping's column belongs to TABLE_NAME (not a JOIN_CONFIG table), and —
		mirroring order_receipt.py's writable_fieldnames() convention — it isn't read_only,
		virtual, or a no-value fieldtype in the DocType's meta (read_only in particular is how
		a server-generated column like a SQL Server IDENTITY field, e.g. AscendProduct.id, is
		marked). 'name' is only included when include_name is True: db_update writes it into
		the WHERE clause instead of SET, while db_insert must supply it as a normal column value.

		field_overrides supplies framework-resolved values (currently just the CreatorID/
		ModifierID attribution built by _resolve_attribution_overrides) that must reach SQL
		regardless of the read_only/virtual/no-value gate below — that gate exists to stop a
		user-edited value from reaching a server-managed column, which doesn't apply to a value
		the framework itself computed. An override is considered even for a field with no entry
		in self.as_dict() at all (e.g. a SCHEMA_CONFIG mapping with no matching declared field)."""
		field_overrides = field_overrides or {}
		document_values = self.as_dict()
		writable_fields = []
		for field in dict.fromkeys([*document_values.keys(), *field_overrides.keys()]):
			if field in field_overrides:
				value = field_overrides[field]
			else:
				if field == 'name':
					if not include_name:
						continue
				else:
					meta_field = self.meta.get_field(field)
					if meta_field and (
						meta_field.read_only or meta_field.is_virtual
						or meta_field.fieldtype in frappe.model.no_value_fields
					):
						continue
				value = self._normalize_write_value(field, document_values[field])

			# Resolved through _field_config rather than _column_for so that NAME_EXPRESSION can
			# never reach a write: a computed expression is not a column and must not appear in
			# an INSERT/UPDATE column list. Do not "simplify" this to _column_for.
			field_config = self._field_config(field)
			if field_config is None or field_config['sql'] is None:
				continue
			if not self._column_belongs_to_table(field):
				if self.SHOW_FIELD_WARNINGS:
					print_console_warning(
						f"Ascend Virtual Doc Warning: Skipping '{field}' for {self.doctype} — "
						f"column '{field_config['sql']}' does not belong to {self.TABLE_NAME}."
					)
				continue
			writable_fields.append((field_config['sql'], value))
		return writable_fields

	def _resolve_linked_id_fields(self) -> None:
		"""Resolve every 'linked_id' display field to the id it references and write that id onto
		the paired id field, so the writable foreign-key column on TABLE_NAME reflects the user's
		edit to the (read-only, JOIN-sourced) display field.

		A display field maps to a joined column that cannot be written directly (e.g. 'category'
		-> 'cat.Topic'); its foreign key lives on TABLE_NAME as a paired id field (e.g. 'category_id'
		-> 'Products.TopicID'). Because the display field is a Link to another virtual DocType, the
		id is resolved through that DocType's get_values — the chosen display value is exactly the
		linked record's primary key, and link_id_field names the column holding its id.

		Resolution is change-triggered: on update, a display field whose value already matches the
		persisted record is left untouched. This avoids a lookup on every save when nothing changed
		and, critically, avoids clobbering the id field when a record that loaded with an empty or
		unresolvable display value (e.g. an orphaned foreign key whose JOIN yields NULL) is saved
		after an unrelated edit. On insert there is no prior record, so every mapping is resolved.

		The resolved id is set on the document before _collect_writable_fields runs, so it is written
		as a normal TABLE_NAME column. An empty display value clears the id field. A non-empty display
		value aborts the save with frappe.throw when it resolves to no linked record (the user picked a
		value the framework cannot resolve an id for — silently writing a stale or NULL id would
		corrupt the record) or to more than one (an ambiguous name yields no single id to write)."""
		linked_id_fields = self.linked_id_fields()
		if not linked_id_fields:
			return

		previous = None if self.is_new() else self.get_latest()

		for display_field, config in linked_id_fields.items():
			display_value = self.get(display_field)
			if previous is not None and previous.get(display_field) == display_value:
				continue

			id_field = config['id_field']
			link_doctype = config['link_doctype']
			link_id_field = config['link_id_field']

			if not display_value:
				self.set(id_field, None)
				continue

			linked_controller = get_controller(link_doctype)
			match_count = linked_controller.get_count(
				doctype=link_doctype, filters=[(None, 'name', '=', display_value)], fields=[],
				distinct=False, save_user_settings=False, strict=None,
			)
			if match_count > 1:
				frappe.throw(
					f"Cannot save {self.doctype} '{self.name}': {display_field} '{display_value}' "
					f"matches {match_count} {link_doctype} records, so its {id_field} is ambiguous. "
					f"The {link_doctype} name must be unique to resolve a single id."
				)

			resolved = linked_controller.get_values(display_value, [link_id_field])
			if not resolved or resolved.get(link_id_field) is None:
				frappe.throw(
					f"Cannot save {self.doctype} '{self.name}': {display_field} '{display_value}' "
					f"does not resolve to a {link_doctype} record, so its {id_field} cannot be "
					f"determined. Choose a value that exists in {link_doctype}."
				)
			self.set(id_field, resolved.get(link_id_field))

	def _resolve_attribution_overrides(self, *, include_creator: bool) -> dict:
		"""Build the field_overrides _collect_writable_fields needs to attribute a
		CreatorID/ModifierID-style write to a real Ascend Users.ID rather than the Frappe
		email string that lives in self.owner/self.modified_by. Only touches 'creator_id'/
		'modified_by' when the subclass has actually mapped them to a writable TABLE_NAME
		column — most virtual DocTypes don't declare either, and a JOIN-sourced mapping (e.g.
		AscendProduct's 'modified_by' -> modifier.Initials) is read-only, so resolving it would
		be wasted work and could needlessly block a save over an unrelated Settings gap.

		self.owner and self.modified_by are never mutated here — only the values returned in
		the override dict are affected, so Frappe's own version tracking and 'Last Modified
		By' display keep seeing real Frappe user emails.

		'creator_id' only resolves when include_creator is True (db_insert only) — CreatorID
		is meant to be immutable after creation, so db_update omits it here, and the field
		falls back to its normal read_only-gated (i.e. untouched) handling."""
		overrides = {}
		resolved_by_frappe_user = {}

		def resolve(frappe_user):
			if frappe_user not in resolved_by_frappe_user:
				try:
					resolved_by_frappe_user[frappe_user] = resolve_attributed_ascend_user_id(frappe_user)
				except AscendAttributionUserNotConfigured:
					frappe.throw(
						f"Cannot save {self.doctype} '{self.name}': '{frappe_user}' has no linked "
						f"Ascend User, and Bullwheel Settings' default_user does not resolve to one "
						f"either. Link a User to an Ascend User, or configure a valid default_user."
					)
			return resolved_by_frappe_user[frappe_user]

		if include_creator and self._column_belongs_to_table('creator_id'):
			overrides['creator_id'] = resolve(self.owner)
		if self._column_belongs_to_table('modified_by'):
			overrides['modified_by'] = resolve(self.modified_by)

		return overrides

	def _resolve_insert_defaults(self) -> dict:
		"""Build the field_overrides carrying this controller's INSERT_DEFAULTS, limited to the
		fields the document has no value of its own for. A default is a floor, not an override:
		anything the user actually entered wins, so this yields on any non-None document value
		(and, being applied before the attribution overrides, on those too).

		A field the DocType never declares is absent from self.as_dict() entirely, which is
		precisely the case this exists for — _collect_writable_fields considers a field present
		only in field_overrides, so the column reaches the INSERT even with no field behind it.

		A callable default is invoked here, at insert time, rather than once when INSERT_DEFAULTS
		is defined — the timestamp-style default this exists for (e.g. Products.ConcurrencyToken)
		would otherwise carry the moment the class was imported for the life of the process. A
		callable returning None means no default is available (e.g. a Bullwheel Settings field
		left unconfigured); that field is left out entirely rather than writing an explicit NULL."""
		if not self.INSERT_DEFAULTS:
			return {}

		document_values = self.as_dict()
		overrides = {}
		for field, default in self.INSERT_DEFAULTS.items():
			if document_values.get(field) is not None:
				continue
			value = default() if callable(default) else default
			if value is None:
				continue
			overrides[field] = value
		return overrides

	def db_insert(self, *args, **kwargs):
		"""Insert this document as a new row in TABLE_NAME. Frappe performs no name-uniqueness
		check for virtual doctypes before calling db_insert (unlike a real doctype, where the
		database's own primary-key constraint catches a collision), so this method runs its own
		pre-flight existence check and raises frappe.DuplicateEntryError rather than silently
		creating a duplicate record."""
		if not self.ALLOW_WRITE:
			raise NotImplementedError(f"{self.doctype} is read-only.")
		if self.NAME_EXPRESSION:
			frappe.throw(
				f"Cannot insert {self.doctype}: NAME_EXPRESSION is a computed SQL expression "
				f"and cannot be supplied directly in an INSERT."
			)
		if not self.name:
			frappe.throw(f"Cannot insert {self.doctype}: no primary key value set.")
		if self._record_exists(self.name):
			frappe.throw(f"{self.doctype} '{self.name}' already exists.", frappe.DuplicateEntryError)

		self._resolve_linked_id_fields()
		# Attribution last: a CreatorID/ModifierID resolved by the framework outranks a default.
		field_overrides = {
			**self._resolve_insert_defaults(),
			**self._resolve_attribution_overrides(include_creator=True),
		}
		writable_fields = self._collect_writable_fields(include_name=True, field_overrides=field_overrides)
		if not writable_fields:
			frappe.throw(f"{self.doctype}: no writable SCHEMA_CONFIG columns resolve for db_insert.")

		columns = ', '.join(column for column, _ in writable_fields)
		placeholders = ', '.join(['%s'] * len(writable_fields))
		values = [value for _, value in writable_fields]
		query = f'INSERT INTO {self.TABLE_NAME} ({columns}) VALUES ({placeholders})'

		with MSSQLDatabase(get_default_ascend_database()) as db:
			db.sql(query=query, values=values, as_dict=False)
			inserted_row_count = db.cursor.rowcount
			if inserted_row_count != 1:
				frappe.throw(
					f"Insert into {self.TABLE_NAME} for {self.doctype} '{self.name}' affected "
					f"{inserted_row_count} rows instead of exactly one."
				)

	def db_update(self, *args, **kwargs):
		"""Push every SCHEMA_CONFIG-mapped field on this document back to its row in TABLE_NAME.
		Fields are read off the document itself (SCHEMA_CONFIG entries are only a suggestion —
		not every mapped fieldname is guaranteed to exist on the Document), and only columns
		that belong to TABLE_NAME are writable; JOIN_CONFIG columns are read-only. The UPDATE's
		affected-row-count is checked after execution and the whole write is rolled back unless
		it touched exactly the one associated record."""
		if not self.ALLOW_WRITE:
			raise NotImplementedError(f"{self.doctype} is read-only.")

		if not self.name:
			frappe.throw(f"Cannot update {self.doctype}: no primary key value set.")

		self._resolve_linked_id_fields()
		attribution_overrides = self._resolve_attribution_overrides(include_creator=False)
		writable_fields = self._collect_writable_fields(include_name=False, field_overrides=attribution_overrides)
		if not writable_fields:
			frappe.throw(f"{self.doctype}: no writable SCHEMA_CONFIG columns resolve for db_update.")

		values = [value for _, value in writable_fields]
		where_clause = self._build_where_clause(values=values, filters=[(None, 'name', '=', self.name)])
		query = (
			f'UPDATE {self.TABLE_NAME} SET '
			+ ', '.join(f'{column} = %s' for column, _ in writable_fields)
			+ ' ' + where_clause
		)

		with MSSQLDatabase(get_default_ascend_database()) as db:
			db.sql(query=query, values=values, as_dict=False)
			updated_row_count = db.cursor.rowcount

			if updated_row_count == 0:
				raise frappe.DoesNotExistError(f"{self.doctype} '{self.name}' could not be updated: no matching record found.")
			if updated_row_count > 1:
				frappe.throw(
					f"Refusing to update {self.doctype} '{self.name}': the WHERE clause matched "
					f"{updated_row_count} records instead of exactly one. This likely indicates a "
					f"SCHEMA_CONFIG misconfiguration (most likely an 'alternate_name' field that is "
					f"not actually unique in Ascend)."
				)

	def delete(self, *args, **kwargs):
		frappe.throw(f"No! Bad user! Never delete {self.doctype} records!")