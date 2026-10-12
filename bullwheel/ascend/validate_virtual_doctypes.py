# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Validation for Virtual DocType SCHEMA_CONFIGs.

All schema-validation concerns for the Virtual DocType framework live here, keeping
`virtual_doctype_base.py` purely runtime. `validate_schema_config` checks a single
controller's config for structural correctness (and, optionally, against introspected
SQL Server columns). `validate_all_virtual_doctype_schemas` runs it for every virtual
DocType in the site and is wired to the `before_migrate` hook, so a misconfigured
controller blocks `bench migrate` with the exact problem named instead of failing at
query time with invalid SQL.
"""

import re

import frappe
from frappe.model import no_value_fields
from frappe.model.base_document import get_controller

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType
from bullwheel.ascend.schema_config import strip_column_quoting
from bullwheel.ascend.schema_introspection import introspect_table_schema, introspect_join_schemas
from bullwheel.bullwheel_core import get_default_ascend_database, print_console_warning


def bare_column(sql_column: str) -> str:
	"""Normalize a SQL column name to its bare, lowercase form for comparison against an
	introspected schema. '[Store UPC]' -> 'store upc'."""
	return strip_column_quoting(sql_column).lower()


def _known_table_qualifiers(doctype_class) -> set:
	"""Table names and aliases a qualified column reference may legally use: the primary
	TABLE_NAME plus every table/alias declared in JOIN_CONFIG."""
	qualifiers = {doctype_class.TABLE_NAME}
	for config in (doctype_class.JOIN_CONFIG or []):
		if config.get('alias'):
			qualifiers.add(config['alias'])
		if config.get('table'):
			qualifiers.add(config['table'])
	return qualifiers


def validate_schema_config(doctype_class, discovered_columns=None, additional_discovered_columns=None) -> bool:
	"""Validate a virtual DocType class's SCHEMA_CONFIG for structural correctness.

	Normalizing the config (see schema_config.py) is itself the primary structural gate: it
	rejects an entry that is not a dict, names an unknown option key, omits its 'column',
	carries a table-qualified column, or gives a non-boolean flag.
	On top of that this function checks that SCHEMA_CONFIG is not empty, that the primary key
	is defined (either a 'name' entry or a NAME_EXPRESSION), that no field claims to be an
	alternate name for 'name' itself, and that every field's table is the primary table or
	declared in JOIN_CONFIG. When NAME_EXPRESSION is set, its table/alias qualifiers are
	checked the same way — by regex, since it is a raw SQL string rather than a structured
	table/column pair — so an undeclared join surfaces here instead of as an opaque SQL bind
	error at query time.

	When discovered_columns is provided (an iterable of SQL column names from the primary
	table, e.g. from introspect_table_schema), confirms that columns on the primary table
	exist in that set. When additional_discovered_columns is provided (column names from
	joined tables), confirms the same for columns on a JOIN_CONFIG table. Joined columns are
	skipped when additional_discovered_columns is not provided. The 'name' entry is skipped
	from column-existence checks when NAME_EXPRESSION is set, since an expression is not a
	plain column.

	Returns True on success; raises ValueError describing the first problem found.
	"""
	class_name = doctype_class.__name__
	name_expression = doctype_class.NAME_EXPRESSION

	if not doctype_class.SCHEMA_CONFIG:
		raise ValueError(f"{class_name}: SCHEMA_CONFIG is empty or None.")

	# Normalize through the controller so the memoized config the query builders will use is
	# exactly the config validated here.
	doctype_class._clear_normalized_schema_cache()
	schema_config = doctype_class._normalized_schema()

	# The primary key must be defined either as a NAME_EXPRESSION or a 'name' entry.
	if not name_expression and (schema_config.get('name') or {}).get('sql') is None:
		raise ValueError(
			f"{class_name}: define the primary key via a SCHEMA_CONFIG 'name' entry naming the "
			f"primary key column, or by setting NAME_EXPRESSION."
		)
	if name_expression is not None and not isinstance(name_expression, str):
		raise ValueError(
			f"{class_name}: NAME_EXPRESSION must be a string SQL expression, got {name_expression!r}."
		)

	# 'name' is the identifier the alternate-name fields are alternatives *to*; marking it as
	# one of its own alternatives would widen a name filter into a meaningless self-OR.
	if (schema_config.get('name') or {}).get('alternate_name'):
		raise ValueError(
			f"{class_name}: the 'name' field cannot set 'alternate_name' — that flag marks the "
			f"other fields a record can be identified by in addition to 'name'."
		)

	# Guardrail: every table/alias a field references must be the primary table or declared in
	# JOIN_CONFIG, otherwise the query fails at runtime with an unknown-name error.
	known_qualifiers = _known_table_qualifiers(doctype_class)
	for fieldname, field_config in schema_config.items():
		table = field_config['table']
		if table is not None and table not in known_qualifiers:
			raise ValueError(
				f"{class_name}: Field '{fieldname}' maps to table/alias '{table}', which is "
				f"neither TABLE_NAME nor a table/alias declared in JOIN_CONFIG."
			)

	# Guardrail: every table/alias a NAME_EXPRESSION qualifies with must be declared, otherwise the
	# query throws a bind error at runtime. Strip bracket-quoted names and string literals first so
	# their internal dots/text don't register as spurious qualifiers.
	if name_expression:
		scannable = re.sub(r"\[[^\]]*\]|'[^']*'", '', name_expression)
		referenced = set(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*\.', scannable))
		unknown = referenced - _known_table_qualifiers(doctype_class)
		if unknown:
			raise ValueError(
				f"{class_name}: NAME_EXPRESSION references undeclared table/alias qualifier(s) "
				f"{sorted(unknown)}. Add them to JOIN_CONFIG or qualify with the primary table "
				f"'{doctype_class.TABLE_NAME}'."
			)

	if discovered_columns is not None or additional_discovered_columns is not None:
		primary_columns = {bare_column(col) for col in discovered_columns} if discovered_columns else None
		joined_columns = {bare_column(col) for col in additional_discovered_columns} if additional_discovered_columns else None

		for fieldname, field_config in schema_config.items():
			if field_config['column'] is None:
				continue
			if fieldname == 'name' and name_expression:
				continue  # An expression-backed primary key is not a plain column.
			# Route by table: a column on the primary table is checked against the primary
			# schema; a column on a JOIN table or alias against the joined-table schema.
			bare = bare_column(field_config['column'])
			if field_config['table'] != doctype_class.TABLE_NAME:
				if joined_columns is not None and bare not in joined_columns:
					raise ValueError(
						f"{class_name}: Field '{fieldname}' maps to joined column "
						f"'{field_config['sql']}', which was not found in the introspected "
						f"joined-table schema."
					)
			else:
				if primary_columns is not None and bare not in primary_columns:
					raise ValueError(
						f"{class_name}: Field '{fieldname}' maps to SQL column "
						f"'{field_config['sql']}', which was not found in the introspected "
						f"primary table schema."
					)

	return True


def autoname_mismatch_reason(controller, autoname: str) -> str | None:
	"""Returns a human-readable reason when `autoname` would make Frappe's own
	BaseDocument._sync_autoname_field() silently corrupt data on every save, or None when
	`autoname` is safe.

	_sync_autoname_field() runs on every save (insert and update) for any DocType whose
	autoname contains 'field:<fieldname>': whenever self.name != self.get(fieldname), it
	force-overwrites <fieldname> with self.name, on the assumption that <fieldname> is what
	the name was *derived from* and has simply drifted out of sync. For a virtual DocType,
	`name` is populated independently via SCHEMA_CONFIG['name']/NAME_EXPRESSION (see
	load_from_db) rather than derived from any one Document field, so that assumption is
	usually false — the mismatch is the normal case, not a sign of drift, and
	_sync_autoname_field ends up clobbering <fieldname> with the primary key value on every
	single save. (Confirmed root cause of a real incident: Ascend Product's leftover
	`autoname = "field:description"` overwrote every saved product's Description with its
	Store UPC.) Any other autoname style (Prompt, hash, naming_series, ...) never triggers
	this path — only a literal 'field:' autoname is affected."""
	if 'field:' not in (autoname or ''):
		return None

	fieldname = autoname.partition('field:')[2]
	schema_config = controller._normalized_schema()

	if controller.NAME_EXPRESSION:
		return (
			f"autoname is 'field:{fieldname}', but NAME_EXPRESSION supplies the primary key — "
			f"there is no literal 'name' column for _sync_autoname_field to keep in sync, so "
			f"it will overwrite '{fieldname}' with the computed primary key value on every save."
		)

	name_column = (schema_config.get('name') or {}).get('sql')
	field_column = (schema_config.get(fieldname) or {}).get('sql')
	if not field_column or not name_column or field_column != name_column:
		return (
			f"autoname is 'field:{fieldname}', but SCHEMA_CONFIG['{fieldname}'] ({field_column!r}) "
			f"does not map to the same column as SCHEMA_CONFIG['name'] ({name_column!r}) — "
			f"_sync_autoname_field will overwrite '{fieldname}' with the primary key value on "
			f"every save."
		)

	return None


def _virtual_doctype_controllers() -> list:
	"""Collect (doctype name, controller class) pairs for every virtual DocType in the site
	whose controller inherits AbstractVirtualDocType."""
	controllers = []
	for doctype_name in frappe.get_all('DocType', filters={'is_virtual': 1}, pluck='name'):
		try:
			controller = get_controller(doctype_name)
		except Exception:
			continue  # Controllers from other apps (or broken imports) are not ours to validate.
		if isinstance(controller, type) and issubclass(controller, AbstractVirtualDocType):
			controllers.append((doctype_name, controller))
	return controllers


def _warn_unmapped_json_fields(doctype_name: str, controller) -> None:
	"""Warn about DocType JSON fields with no SCHEMA_CONFIG mapping. These are the invalid-SQL
	filters of the future: the desk lets users filter on any declared field, and an unmapped
	one raises at query time. Layout and property-backed virtual fields are exempt."""
	meta = frappe.get_meta(doctype_name)
	for field in meta.fields:
		if field.fieldtype in no_value_fields or field.get('is_virtual'):
			continue
		if controller._field_config(field.fieldname) is None:
			print_console_warning(
				f"Virtual DocType Validation: field '{field.fieldname}' is declared on "
				f"{doctype_name} but has no SCHEMA_CONFIG mapping in {controller.__name__} — "
				f"filtering on it will raise an error."
			)


def _check_autoname_safety(doctype_name: str, controller) -> None:
	"""Warns when the DocType's live `autoname` does not mirror the controller's primary key
	(see autoname_mismatch_reason). Ascend records are read-only in Bullwheel, so no data is
	at risk, but a mismatched autoname still produces confusing record names, so it is worth
	surfacing early."""
	frappe.reload_doctype(doctype_name)
	autoname = frappe.get_meta(doctype_name).autoname
	mismatch_reason = autoname_mismatch_reason(controller, autoname)
	if mismatch_reason:
		print_console_warning(f"Virtual DocType Validation: {doctype_name} — {mismatch_reason}")


def _introspected_columns_for(controller, server_document) -> tuple:
	"""Introspect the controller's primary table and joined tables from the live Ascend
	database. Returns (primary column names, joined column names)."""
	primary_schema = introspect_table_schema(server_document, controller.TABLE_NAME)
	joined_schema = introspect_join_schemas(server_document, controller.JOIN_CONFIG)
	return list(primary_schema.keys()), list(joined_schema.keys())


def validate_all_virtual_doctype_schemas() -> None:
	"""Validate every Bullwheel virtual DocType's SCHEMA_CONFIG. Wired to the before_migrate
	hook: structural problems raise and block the migration, while an unreachable Ascend
	database only downgrades the live column-existence pass to a console warning."""
	controllers = _virtual_doctype_controllers()

	for doctype_name, controller in controllers:
		validate_schema_config(controller)
		_warn_unmapped_json_fields(doctype_name, controller)
		_check_autoname_safety(doctype_name, controller)

	for doctype_name, controller in controllers:
		try:
			primary_columns, joined_columns = _introspected_columns_for(
				controller, get_default_ascend_database()
			)
		except Exception as error:
			print_console_warning(
				f"Virtual DocType Validation: could not introspect the Ascend database for "
				f"{doctype_name} ({error}); skipping live column checks."
			)
			continue
		validate_schema_config(
			controller,
			discovered_columns=primary_columns,
			additional_discovered_columns=joined_columns or None,
		)

	if controllers:
		print(f"Virtual DocType Validation: {len(controllers)} SCHEMA_CONFIG(s) validated.")
