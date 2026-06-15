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

# Allowed values for the `display` key in a SCHEMA_CONFIG entry.
VALID_DISPLAY_VALUES = (None, "hidden", "primary", "secondary")


def build_field_to_column(schema_config, primary_key_column):
	"""Convert SCHEMA_CONFIG into the FIELD_TO_COLUMN dict AscendDatabase uses to
	resolve filter/order fieldnames to SQL column names.

	Fields whose `sql_column` is None (NULL placeholders) are omitted — they
	cannot be filtered or ordered on. The Frappe meta-field `name` is mapped to
	the primary key column so filters referencing `name` resolve without
	special-casing.
	"""
	field_to_column = {}
	for fieldname, field_config in schema_config.items():
		sql_column = field_config.get("sql_column")
		if sql_column:
			field_to_column[fieldname] = sql_column
	field_to_column["name"] = primary_key_column
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


def find_primary_key_field(schema_config, primary_key_column):
	"""Return the fieldname whose `sql_column` is the table's primary key column.

	The result is the key used to populate Frappe's `name` meta-field from a query
	result. Raises ValueError unless exactly one field maps to the primary key,
	which keeps a misconfigured SCHEMA_CONFIG from silently producing nameless rows.
	"""
	matches = [
		fieldname
		for fieldname, field_config in schema_config.items()
		if field_config.get("sql_column") == primary_key_column
	]
	if len(matches) != 1:
		raise ValueError(
			f"Expected exactly one SCHEMA_CONFIG field mapping to primary key "
			f"column '{primary_key_column}', found {len(matches)}: {matches}"
		)
	return matches[0]


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


def validate_schema_config(schema_config, primary_key_column, discovered_columns=None):
	"""Validate a SCHEMA_CONFIG dict, raising ValueError on the first problem found.

	Always checks structural correctness: every entry has the required keys, a
	valid `display` value, and a boolean-ish `searchable`; and exactly one field
	maps to `primary_key_column`.

	When `discovered_columns` (the output of introspect_table_schema, or any
	iterable of real SQL column names) is provided, also confirms every non-NULL
	`sql_column` exists in the table — catching typos before they reach SQL Server.
	Bracket-quoting (`[Store UPC]`) is stripped before comparison.

	Returns True when the config is valid.
	"""
	if not schema_config:
		raise ValueError("SCHEMA_CONFIG is empty.")

	known_columns = {column.lower() for column in discovered_columns} if discovered_columns else None

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
		if known_columns is not None and sql_column:
			bare_column = sql_column.strip("[]").lower()
			if bare_column not in known_columns:
				raise ValueError(
					f"Field '{fieldname}' maps to SQL column '{sql_column}', "
					f"which was not found in the introspected table schema."
				)

	# Reuse the primary-key uniqueness check (raises if not exactly one match).
	find_primary_key_field(schema_config, primary_key_column)
	return True


def _humanize_fieldname(fieldname):
	"""Turn a snake_case fieldname into a Title Case label for JSON scaffolding."""
	return fieldname.replace("_", " ").title()
