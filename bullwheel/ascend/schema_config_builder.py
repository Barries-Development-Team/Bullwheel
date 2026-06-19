# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Config-to-code converters for the Virtual DocType framework.

A single ``SCHEMA_CONFIG`` dict declared on a Virtual DocType controller is the
single source of truth for that DocType's SQL mapping. These builders turn that
one dict into every derived constant the framework needs:

    SCHEMA_CONFIG ─┬─> build_field_to_column()  -> FIELD_TO_COLUMN (filter resolution)
                   ├─> build_select_clause()    -> SELECT_CLAUSE   (aliased projection)
                   ├─> build_search_columns()   -> SEARCH_COLUMNS  (Link autocomplete)
                   └─> build_json_schema()       -> doctype.json `fields` scaffold

``SCHEMA_CONFIG`` maps each Frappe fieldname to a config dict:

    "store_sku": {
        "sql_column": "[Store UPC]",  # bracket-quote names containing spaces; None => SELECT NULL
        "fieldtype": "Data",
        "display": "secondary",        # "hidden" | "primary" | "secondary" | None
        "searchable": True,
    }

`display` controls list-view / autocomplete exposure:
    "hidden"    — included in the document but never shown in the list view (e.g. UUIDs)
    "primary"   — title / Link label; always shown
    "secondary" — shown in lists and Link autocomplete alongside the primary
    None        — not shown in lists, but present in the full document form

`searchable` controls whether the column joins the OR LIKE autocomplete search.
"""

import uuid

# Allowed values for the `display` key in a SCHEMA_CONFIG entry.
VALID_DISPLAY_VALUES = (None, "hidden", "primary", "secondary")


def _bare_column(sql_column):
	"""Extract the unqualified column name from a SQL column reference.

	Handles table-qualified references (`Products.ID`, `cat.Topic`) and bracket-quoted
	names (`[Store UPC]`, `[Year]`). Returns the lowercase column name only, so
	`"Products.ID"`, `"[ID]"`, and `"ID"` all produce `"id"`. Used wherever a column
	name needs to be compared without qualification or bracket decorators.
	"""
	if not sql_column:
		return ""
	return sql_column.split(".")[-1].strip("[]").lower()


def normalize_record(record):
	"""Coerce a SQL result row into Frappe-friendly primitive values.

	pymssql returns SQL Server `uniqueidentifier` (GUID) columns as Python
	`uuid.UUID` objects. Frappe requires *string* identifiers: the `name`
	meta-field, Link field values, and filter values must all be strings — passing
	a UUID into Frappe's query builder raises "Unsupported filters type: UUID", and
	a UUID `name` breaks Link autocomplete and document loading.

	Returns a new dict with every `uuid.UUID` value converted to its string form
	(lowercase, hyphenated; SQL Server compares `uniqueidentifier` case-insensitively,
	so the value still round-trips for lookups). Other values are left unchanged.
	"""
	return {
		fieldname: (str(value) if isinstance(value, uuid.UUID) else value)
		for fieldname, value in record.items()
	}


def build_field_to_column(schema_config):
	"""Convert SCHEMA_CONFIG into the FIELD_TO_COLUMN dict used to resolve filter
	and order-by fieldnames to SQL column names.

	Fields whose `sql_column` is None (NULL placeholders) are omitted — they
	cannot be filtered or ordered on. The `name` entry in SCHEMA_CONFIG is
	handled identically to every other field; it naturally maps Frappe's `name`
	meta-field to the primary key column.
	"""
	field_to_column = {}
	for fieldname, field_config in schema_config.items():
		sql_column = field_config.get("sql_column")
		if sql_column:
			field_to_column[fieldname] = sql_column
	return field_to_column


def build_select_clause(schema_config):
	"""Build a SELECT clause with `AS fieldname` aliases so result dicts are keyed
	by Frappe fieldname directly.

	A field with `sql_column` None is projected as `NULL AS fieldname`, preserving
	the column in the document shape while the real source column is still being
	resolved.
	"""
	select_expressions = []
	for fieldname, field_config in schema_config.items():
		sql_column = field_config.get("sql_column") or "NULL"
		select_expressions.append(f"{sql_column} AS {fieldname}")
	return ", ".join(select_expressions)


def build_search_columns(schema_config):
	"""Extract the SQL column names of every searchable field, in config order.

	These columns are joined with OR LIKE when the user types into a Link field
	autocomplete. Fields with no SQL column are skipped even if marked searchable.
	"""
	return [
		field_config["sql_column"]
		for field_config in schema_config.values()
		if field_config.get("searchable") and field_config.get("sql_column")
	]



def build_json_schema(schema_config):
	"""Generate a doctype.json `fields` array scaffold from SCHEMA_CONFIG.

	Returns a list of Frappe field definition dicts. This is a starting point for a
	new Virtual DocType — labels are derived from fieldnames and section/column
	breaks are not generated, so developers will still arrange and refine the
	result in the DocType editor.

	`display` maps to UI flags:
	    "hidden"                  -> hidden: 1
	    "primary" / "secondary"   -> in_list_view: 1
	Searchable fields get `search_index: 1` (a hint; ignored for virtual tables).
	"""
	fields = []
	for fieldname, field_config in schema_config.items():
		field = {
			"fieldname": fieldname,
			"fieldtype": field_config.get("fieldtype", "Data"),
			"label": _humanize_fieldname(fieldname),
		}

		display = field_config.get("display")
		if display == "hidden":
			field["hidden"] = 1
		elif display in ("primary", "secondary"):
			field["in_list_view"] = 1

		if field_config.get("searchable"):
			field["search_index"] = 1

		fields.append(field)
	return fields


def validate_schema_config(
	schema_config,
	discovered_columns=None,
	additional_discovered_columns=None,
):
	"""Validate a SCHEMA_CONFIG dict, raising ValueError on the first problem found.

	Always checks structural correctness: every entry has the required keys and a
	valid `display` value; and a `name` entry with a non-null `sql_column` is present
	(the `name` entry is what maps Frappe's primary identifier to a SQL column).

	When `discovered_columns` (the output of `introspect_table_schema`, or any
	iterable of real SQL column names) is provided, confirms every non-NULL,
	unqualified `sql_column` exists in the primary table.

	When `additional_discovered_columns` (a flat iterable of column names from
	joined tables, e.g. from `introspect_join_schemas`) is provided, confirms
	table-qualified `sql_column` references (those containing `.`) resolve to a
	known column in the joined tables. Bracket-quoting is stripped before comparison.

	Unqualified columns are checked against `discovered_columns` only.
	Table-qualified columns (`table.column`) are checked against
	`additional_discovered_columns` only; if that is not provided, qualified columns
	are skipped (the developer is responsible for verifying joined-table column names).

	Returns True when the config is valid.
	"""
	if not schema_config:
		raise ValueError("SCHEMA_CONFIG is empty.")

	if "name" not in schema_config:
		raise ValueError(
			"SCHEMA_CONFIG must include a 'name' entry mapping sql_column to the primary key column."
		)
	if not schema_config["name"].get("sql_column"):
		raise ValueError(
			"SCHEMA_CONFIG 'name' entry must have a non-null sql_column (the primary key column)."
		)

	primary_columns = {_bare_column(col) for col in discovered_columns} if discovered_columns else None
	joined_columns = {_bare_column(col) for col in additional_discovered_columns} if additional_discovered_columns else None

	for fieldname, field_config in schema_config.items():
		if "sql_column" not in field_config:
			raise ValueError(f"Field '{fieldname}' is missing the required 'sql_column' key.")
		if "fieldtype" not in field_config:
			raise ValueError(f"Field '{fieldname}' is missing the required 'fieldtype' key.")

		display = field_config.get("display")
		if display not in VALID_DISPLAY_VALUES:
			raise ValueError(
				f"Field '{fieldname}' has invalid display '{display}'. "
				f"Expected one of {VALID_DISPLAY_VALUES}."
			)

		sql_column = field_config.get("sql_column")
		if sql_column:
			is_qualified = "." in sql_column
			bare = _bare_column(sql_column)
			if is_qualified:
				if joined_columns is not None and bare not in joined_columns:
					raise ValueError(
						f"Field '{fieldname}' maps to joined column '{sql_column}', "
						f"which was not found in the introspected joined-table schema."
					)
			else:
				if primary_columns is not None and bare not in primary_columns:
					raise ValueError(
						f"Field '{fieldname}' maps to SQL column '{sql_column}', "
						f"which was not found in the introspected table schema."
					)

	return True


def _humanize_fieldname(fieldname):
	"""Turn a snake_case fieldname into a Title Case label for JSON scaffolding."""
	return fieldname.replace("_", " ").title()
