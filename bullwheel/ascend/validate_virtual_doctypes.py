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
from bullwheel.ascend.schema_introspection import introspect_table_schema, introspect_join_schemas
from bullwheel.bullwheel_core import get_default_ascend_database, print_console_warning


def bare_column(sql_column: str) -> str:
	"""Extract the bare, lowercase column name from a SQL column reference for comparison.
	Handles table-qualified references ('Products.ID', 'cat.Topic') and bracket-quoted
	names ('[Store UPC]', '[Year]'). 'Products.[Store UPC]' -> 'store upc'."""
	return sql_column.split('.')[-1].strip('[]').lower()


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

	Always checks that SCHEMA_CONFIG is not empty, that the primary key is defined
	(either a non-null 'name' entry or a NAME_EXPRESSION), that all values are strings
	or None, and that every ALT_NAME_RESOLUTION_FIELDS entry has a non-null mapping.
	When NAME_EXPRESSION is set, its table/alias qualifiers are checked against
	TABLE_NAME + JOIN_CONFIG so an undeclared join surfaces here instead of as an
	opaque SQL bind error at query time.

	When discovered_columns is provided (an iterable of SQL column names from the primary
	table, e.g. from introspect_table_schema), confirms that unqualified column references
	exist in that set. When additional_discovered_columns is provided (column names from
	joined tables), confirms that table-qualified references (containing '.') resolve to a
	known column. Qualified columns are skipped when additional_discovered_columns is not
	provided. The 'name' entry is skipped from column-existence checks when NAME_EXPRESSION
	is set, since an expression is not a plain column.

	Returns True on success; raises ValueError describing the first problem found.
	"""
	class_name = doctype_class.__name__
	schema_config = doctype_class.SCHEMA_CONFIG
	name_expression = doctype_class.NAME_EXPRESSION

	if not schema_config:
		raise ValueError(f"{class_name}: SCHEMA_CONFIG is empty or None.")

	# The primary key must be defined either as a NAME_EXPRESSION or a non-null 'name' entry.
	if not name_expression and not schema_config.get('name'):
		raise ValueError(
			f"{class_name}: define the primary key via a non-null SCHEMA_CONFIG 'name' entry "
			f"or by setting NAME_EXPRESSION."
		)
	if name_expression is not None and not isinstance(name_expression, str):
		raise ValueError(
			f"{class_name}: NAME_EXPRESSION must be a string SQL expression, got {name_expression!r}."
		)

	for fieldname, sql_column in schema_config.items():
		if sql_column is not None and not isinstance(sql_column, str):
			raise ValueError(
				f"{class_name}: Field '{fieldname}' has an invalid value {sql_column!r}. "
				f"Expected a string SQL column name or None."
			)

	# Every alternative name-resolution field must resolve to a real mapping, since
	# _condition_sql widens 'name' filters across them without re-checking.
	for alt_field in (doctype_class.ALT_NAME_RESOLUTION_FIELDS or []):
		if not schema_config.get(alt_field):
			raise ValueError(
				f"{class_name}: ALT_NAME_RESOLUTION_FIELDS entry '{alt_field}' has no "
				f"SCHEMA_CONFIG mapping."
			)

	# Guardrail: every table/alias a qualified sql_column references must be the primary table
	# or declared in JOIN_CONFIG, otherwise the query fails at runtime with an unknown-name error.
	known_qualifiers = _known_table_qualifiers(doctype_class)
	for fieldname, sql_column in schema_config.items():
		if sql_column and '.' in sql_column:
			qualifier = sql_column.split('.')[0]
			if qualifier not in known_qualifiers:
				raise ValueError(
					f"{class_name}: Field '{fieldname}' maps to '{sql_column}', but qualifier "
					f"'{qualifier}' is neither TABLE_NAME nor a table/alias declared in JOIN_CONFIG."
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

		for fieldname, sql_column in schema_config.items():
			if not sql_column:
				continue
			if fieldname == 'name' and name_expression:
				continue  # An expression-backed primary key is not a plain column.
			# Route by qualifier: a column qualified with the primary table (or unqualified)
			# is checked against the primary schema; a column qualified with a JOIN table or
			# alias is checked against the joined-table schema.
			qualifier = sql_column.split('.')[0] if '.' in sql_column else None
			bare = bare_column(sql_column)
			if qualifier is not None and qualifier != doctype_class.TABLE_NAME:
				if joined_columns is not None and bare not in joined_columns:
					raise ValueError(
						f"{class_name}: Field '{fieldname}' maps to joined column '{sql_column}', "
						f"which was not found in the introspected joined-table schema."
					)
			else:
				if primary_columns is not None and bare not in primary_columns:
					raise ValueError(
						f"{class_name}: Field '{fieldname}' maps to SQL column '{sql_column}', "
						f"which was not found in the introspected primary table schema."
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
	schema_config = controller.SCHEMA_CONFIG or {}

	if controller.NAME_EXPRESSION:
		return (
			f"autoname is 'field:{fieldname}', but NAME_EXPRESSION supplies the primary key — "
			f"there is no literal 'name' column for _sync_autoname_field to keep in sync, so "
			f"it will overwrite '{fieldname}' with the computed primary key value on every save."
		)

	name_column = schema_config.get('name')
	field_column = schema_config.get(fieldname)
	if not field_column or not name_column or bare_column(field_column) != bare_column(name_column):
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
		if controller.SCHEMA_CONFIG.get(field.fieldname) is None:
			print_console_warning(
				f"Virtual DocType Validation: field '{field.fieldname}' is declared on "
				f"{doctype_name} but has no SCHEMA_CONFIG mapping in {controller.__name__} — "
				f"filtering on it will raise an error."
			)


def _check_autoname_safety(doctype_name: str, controller) -> None:
	"""Checks the DocType's live `autoname` against autoname_mismatch_reason(). A write-enabled
	DocType (ALLOW_WRITE=True) with an unsafe autoname blocks the migration outright, since the
	next save would silently corrupt Ascend data (see autoname_mismatch_reason's docstring for
	the exact mechanism). A read-only DocType only gets a console warning — no data is at risk
	yet, but the same misconfiguration will corrupt data the moment ALLOW_WRITE is flipped on,
	so it's worth surfacing early rather than waiting to rediscover it the same way."""
	frappe.reload_doctype(doctype_name)
	autoname = frappe.get_meta(doctype_name).autoname
	mismatch_reason = autoname_mismatch_reason(controller, autoname)
	if not mismatch_reason:
		return

	if controller.ALLOW_WRITE:
		raise ValueError(
			f"{doctype_name}: {mismatch_reason} Set autoname = 'Prompt' on the DocType, or "
			f"point 'field:' at a field whose SCHEMA_CONFIG mapping mirrors the primary key "
			f"column, before enabling ALLOW_WRITE."
		)

	print_console_warning(
		f"Virtual DocType Validation: {doctype_name} — {mismatch_reason} This DocType is "
		f"currently read-only (ALLOW_WRITE=False), so no data is at risk yet, but this will "
		f"corrupt data the moment ALLOW_WRITE is enabled."
	)


def _linked_id_field_structural_problems(controller) -> list:
	"""Collect the SCHEMA_CONFIG-only violations of the LINKED_ID_FIELDS convention — the checks
	that need no DocType meta. Each entry must name the required keys, its display field and id_field
	must both be in SCHEMA_CONFIG, the id_field must map to a column on TABLE_NAME (a JOIN column
	can't be written), and link_doctype/link_id_field must resolve to a real linked virtual DocType
	controller and one of its mapped fields. Returns a list of problem strings (empty when sound)."""
	problems = []
	schema_config = controller.SCHEMA_CONFIG or {}
	linked_id_fields = controller.LINKED_ID_FIELDS or {}

	for display_field, config in linked_id_fields.items():
		if not isinstance(config, dict) or not all(key in config for key in ('id_field', 'link_doctype', 'link_id_field')):
			problems.append(
				f"LINKED_ID_FIELDS['{display_field}'] must be a dict with 'id_field', "
				f"'link_doctype', and 'link_id_field' keys."
			)
			continue

		id_field = config['id_field']
		link_doctype = config['link_doctype']
		link_id_field = config['link_id_field']

		if display_field not in schema_config:
			problems.append(f"LINKED_ID_FIELDS display field '{display_field}' has no SCHEMA_CONFIG mapping.")
		if id_field not in schema_config:
			problems.append(f"LINKED_ID_FIELDS['{display_field}'].id_field '{id_field}' has no SCHEMA_CONFIG mapping.")
		elif not controller._column_belongs_to_table(schema_config[id_field]):
			problems.append(
				f"LINKED_ID_FIELDS['{display_field}'].id_field '{id_field}' maps to "
				f"'{schema_config[id_field]}', which is not a column on TABLE_NAME "
				f"'{controller.TABLE_NAME}' and so cannot be written."
			)

		try:
			linked_controller = get_controller(link_doctype)
		except Exception:
			linked_controller = None
		if not (isinstance(linked_controller, type) and issubclass(linked_controller, AbstractVirtualDocType)):
			problems.append(
				f"LINKED_ID_FIELDS['{display_field}'].link_doctype '{link_doctype}' does not resolve "
				f"to a virtual DocType controller."
			)
		elif link_id_field not in (linked_controller.SCHEMA_CONFIG or {}):
			problems.append(
				f"LINKED_ID_FIELDS['{display_field}'].link_id_field '{link_id_field}' has no "
				f"SCHEMA_CONFIG mapping on {link_doctype}."
			)

	return problems


def _linked_id_field_meta_problems(doctype_name: str, controller) -> list:
	"""Collect the meta-dependent violations of the LINKED_ID_FIELDS convention. Each pairing's
	id_field must be a declared, non-read-only DocType field (a read-only or undeclared id field
	would never be written, re-introducing the silent data loss this convention closes). And for
	coverage: every editable DocType field (declared, not read-only, not virtual, not a no-value
	fieldtype) whose SCHEMA_CONFIG column lives on a JOIN table rather than TABLE_NAME must be paired
	via LINKED_ID_FIELDS — otherwise a user's edit to it silently vanishes on save."""
	problems = []
	schema_config = controller.SCHEMA_CONFIG or {}
	linked_id_fields = controller.LINKED_ID_FIELDS or {}
	meta = frappe.get_meta(doctype_name)

	for display_field, config in linked_id_fields.items():
		if not isinstance(config, dict) or 'id_field' not in config:
			continue  # Malformed entries are reported by the structural pass.
		id_field = config['id_field']
		id_meta_field = meta.get_field(id_field)
		if not id_meta_field:
			problems.append(
				f"LINKED_ID_FIELDS['{display_field}'].id_field '{id_field}' is not a declared "
				f"field on {doctype_name}, so its resolved id would never be written."
			)
		elif id_meta_field.read_only:
			problems.append(
				f"LINKED_ID_FIELDS['{display_field}'].id_field '{id_field}' is read_only on "
				f"{doctype_name}; a read-only id field is never written. Make it hidden but not read_only."
			)

	for field in meta.fields:
		if field.fieldtype in no_value_fields or field.get('is_virtual') or field.read_only:
			continue
		sql_column = schema_config.get(field.fieldname)
		if sql_column is None:
			continue  # Unmapped fields are reported by _warn_unmapped_json_fields.
		if not controller._column_belongs_to_table(sql_column) and field.fieldname not in linked_id_fields:
			problems.append(
				f"Field '{field.fieldname}' is editable and maps to JOIN column '{sql_column}' "
				f"(not on TABLE_NAME '{controller.TABLE_NAME}'), but has no LINKED_ID_FIELDS pairing. "
				f"Edits to it would silently vanish on save. Pair it with a writable id field via "
				f"LINKED_ID_FIELDS, or mark it read_only."
			)

	return problems


def _check_linked_id_fields(doctype_name: str, controller) -> None:
	"""Enforce the LINKED_ID_FIELDS convention. On a write-enabled DocType (ALLOW_WRITE=True) any
	violation blocks the migration, since the next save would either silently drop a joined-field
	edit or fail to write a resolved id. A read-only DocType only gets a console warning — no data
	is at risk yet, but the same misconfiguration bites the moment ALLOW_WRITE is enabled. Mirrors
	_check_autoname_safety's severity split."""
	problems = (
		_linked_id_field_structural_problems(controller)
		+ _linked_id_field_meta_problems(doctype_name, controller)
	)
	if not problems:
		return

	joined = '\n  - '.join(problems)
	if controller.ALLOW_WRITE:
		raise ValueError(f"{doctype_name}: LINKED_ID_FIELDS convention violated:\n  - {joined}")

	print_console_warning(
		f"Virtual DocType Validation: {doctype_name} — LINKED_ID_FIELDS convention violated (this "
		f"DocType is currently read-only, so no data is at risk yet, but this will corrupt data the "
		f"moment ALLOW_WRITE is enabled):\n  - {joined}"
	)


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
		_check_linked_id_fields(doctype_name, controller)

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
