# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""The SCHEMA_CONFIG field-config contract for the Virtual DocType framework.

A virtual DocType controller declares one `SCHEMA_CONFIG` dict describing every field
it surfaces. Each entry is a dict of per-field options, so everything the framework
knows about a field lives in one place:

	SCHEMA_CONFIG = {
		'name':        {'column': 'Store UPC', 'static': True},
		'upc':         {'column': 'UPC', 'alternate_name': True},
		'description': {'column': 'Description'},
		'category':    {'table': 'cat', 'column': 'Topic',
		                'linked_id': {'id_field': 'category_id',
		                              'link_doctype': 'Product Category',
		                              'link_id_field': 'database_id'}},
	}

Authored entries are expanded once per controller into a canonical internal form by
`normalize_schema_config`, which fills the implied `table`, pre-computes the qualified
SQL reference the query builders splice into their clauses, and rejects unknown or
wrongly-typed keys. Keeping that contract here (rather than in the runtime base class)
lets `virtual_doctype_base.py` stay query-focused while
`validate_virtual_doctypes.py` validates against the very same key definitions.

Field config keys:

	column          Required. The bare SQL column name — unqualified and unquoted.
	                The framework adds the table qualifier and bracket-quoting, so
	                'Store UPC' and 'Year' need no special handling by the author.
	table           Optional. The table name or JOIN_CONFIG alias the column belongs
	                to. Defaults to the controller's TABLE_NAME, so only fields
	                sourced from a joined table need to name one.
	alternate_name  Optional bool. Marks an additional field a record can be
	                identified by, alongside 'name' (e.g. UPC as well as Store SKU).
	                Every filter on 'name' widens to an OR across these fields, so
	                they must be unique in the Ascend database.
	static          Optional bool. The value never changes for a given record (an
	                identity column, a creation timestamp), so it is safe to cache.
	                Declarative only for now — no caching layer reads it yet.
	linked_id       Optional dict. Pairs an editable field whose column lives on a
	                JOIN table with the writable foreign-key field on TABLE_NAME that
	                stores its id. Requires 'id_field', 'link_doctype' and
	                'link_id_field'. See _resolve_linked_id_fields.

An entry may also be `None`, declaring a field as deliberately unmapped.

Note that a field config cannot hold a raw SQL expression: bracket-quoting is
unconditional, and `[CONCAT(...)]` is not valid SQL. A computed primary key is
declared with the controller's NAME_EXPRESSION attribute instead.
"""

FIELD_CONFIG_KEYS = frozenset({'column', 'table', 'alternate_name', 'static', 'linked_id'})

BOOLEAN_FIELD_CONFIG_KEYS = ('alternate_name', 'static')

LINKED_ID_KEYS = frozenset({'id_field', 'link_doctype', 'link_id_field'})


def quote_column(column: str) -> str:
	"""Bracket-quote a bare SQL Server column name so names containing spaces ('Store UPC')
	and reserved words ('Year') are always safe to splice into a query. Any quoting the
	author already supplied is stripped first, so '[Store UPC]' and 'Store UPC' produce
	the same result."""
	return f'[{strip_column_quoting(column)}]'


def strip_column_quoting(column: str) -> str:
	"""Remove bracket, backtick, or double-quote wrapping from a SQL column name."""
	return column.strip().strip('[]`"')


def normalize_field_config(class_name: str, fieldname: str, field_config, table_name: str) -> dict:
	"""Expand one authored SCHEMA_CONFIG entry into its canonical internal form.

	Fills 'table' from the controller's TABLE_NAME when the entry does not name one, and
	pre-computes the qualified, bracket-quoted 'sql' reference the query builders use — so
	resolving a field at query time stays a single dict lookup. A `None` entry declares a
	deliberately unmapped field and normalizes to an all-empty config.

	Raises ValueError naming the class and field for an unknown key, a wrongly-typed
	value, or a column that still carries a table qualifier (the hallmark of an entry
	half-converted from the older flat 'Table.Column' format)."""
	if field_config is None:
		return {
			'column': None, 'table': None, 'sql': None,
			'alternate_name': False, 'static': False, 'linked_id': None,
		}

	if not isinstance(field_config, dict):
		raise ValueError(
			f"{class_name}: Field '{fieldname}' has an invalid config {field_config!r}. "
			f"Expected a dict of field options (e.g. {{'column': 'Description'}}) or None."
		)

	unknown_keys = set(field_config) - FIELD_CONFIG_KEYS
	if unknown_keys:
		raise ValueError(
			f"{class_name}: Field '{fieldname}' has unknown config key(s) {sorted(unknown_keys)}. "
			f"Valid keys are {sorted(FIELD_CONFIG_KEYS)}."
		)

	column = field_config.get('column')
	if not isinstance(column, str) or not strip_column_quoting(column):
		raise ValueError(
			f"{class_name}: Field '{fieldname}' is missing a 'column'. Expected a bare SQL "
			f"column name, got {column!r}."
		)
	if '.' in column:
		raise ValueError(
			f"{class_name}: Field '{fieldname}' has a table-qualified column {column!r}. "
			f"Give the bare column name and name its table with the 'table' key instead."
		)

	table = field_config.get('table', table_name)
	if not isinstance(table, str) or not table.strip():
		raise ValueError(
			f"{class_name}: Field '{fieldname}' has an invalid 'table' {table!r}. Expected a "
			f"table name or JOIN_CONFIG alias, or omit the key to use TABLE_NAME."
		)

	normalized = {
		'column': strip_column_quoting(column),
		'table': table,
		'sql': f'{table}.{quote_column(column)}',
		'linked_id': _normalized_linked_id(class_name, fieldname, field_config.get('linked_id')),
	}

	for key in BOOLEAN_FIELD_CONFIG_KEYS:
		value = field_config.get(key, False)
		if not isinstance(value, bool):
			raise ValueError(
				f"{class_name}: Field '{fieldname}' has a non-boolean '{key}' value {value!r}."
			)
		normalized[key] = value

	return normalized


def _normalized_linked_id(class_name: str, fieldname: str, linked_id) -> dict | None:
	"""Validate a field config's optional 'linked_id' pairing, which must name exactly the
	keys in LINKED_ID_KEYS. Returns the pairing unchanged, or None when absent."""
	if linked_id is None:
		return None

	if not isinstance(linked_id, dict):
		raise ValueError(
			f"{class_name}: Field '{fieldname}' has an invalid 'linked_id' {linked_id!r}. "
			f"Expected a dict with keys {sorted(LINKED_ID_KEYS)}."
		)

	missing_keys = LINKED_ID_KEYS - set(linked_id)
	unknown_keys = set(linked_id) - LINKED_ID_KEYS
	if missing_keys or unknown_keys:
		raise ValueError(
			f"{class_name}: Field '{fieldname}' has a malformed 'linked_id'"
			+ (f" — missing key(s) {sorted(missing_keys)}" if missing_keys else '')
			+ (f" — unknown key(s) {sorted(unknown_keys)}" if unknown_keys else '')
			+ f". Expected exactly {sorted(LINKED_ID_KEYS)}."
		)

	for key in sorted(LINKED_ID_KEYS):
		if not isinstance(linked_id[key], str) or not linked_id[key].strip():
			raise ValueError(
				f"{class_name}: Field '{fieldname}' has an invalid 'linked_id' "
				f"'{key}' value {linked_id[key]!r}. Expected a non-empty string."
			)

	return dict(linked_id)


def normalize_schema_config(doctype_class) -> dict:
	"""Expand a controller's whole SCHEMA_CONFIG into its canonical internal form, keyed by
	fieldname and preserving declaration order (the default SELECT projection and the
	alternate-name OR widening both depend on it). An empty or unset SCHEMA_CONFIG
	normalizes to an empty dict; reporting that as a problem is validation's job."""
	return {
		fieldname: normalize_field_config(
			doctype_class.__name__, fieldname, field_config, doctype_class.TABLE_NAME
		)
		for fieldname, field_config in (doctype_class.SCHEMA_CONFIG or {}).items()
	}
