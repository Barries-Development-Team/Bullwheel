# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""SQL Server schema discovery for the Virtual DocType framework.

Before declaring a SCHEMA_CONFIG for a new Ascend table, a developer needs to
know what columns the table actually has and their types. These helpers query
SQL Server's standard `INFORMATION_SCHEMA.COLUMNS` view to discover that, so the
config can be written against verified column names instead of guesses.

This is low-level infrastructure (raw schema queries, not Ascend business
queries), so it uses MSSQLDatabase directly rather than AscendDatabase.

Run it via the CLI — see bullwheel/commands.py:

    bench --site <site> introspect-schema --table Products --suggest --primary-key ID
"""

from bullwheel.database.SQLServer import MSSQLDatabase


def introspect_table_schema(server_document, table_name):
	"""Discover the columns of a SQL Server table via INFORMATION_SCHEMA.COLUMNS.

	`server_document` is a `SQL Server` Frappe document (e.g. from
	get_default_ascend_database). Returns a dict keyed by SQL column name, in the
	table's ordinal column order:

	    {
	        "ID":          {"sql_type": "bigint",  "length": None, "nullable": False},
	        "Description": {"sql_type": "varchar", "length": 255,  "nullable": True},
	        ...
	    }
	"""
	query = (
		"SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE "
		"FROM INFORMATION_SCHEMA.COLUMNS "
		"WHERE TABLE_NAME = %s "
		"ORDER BY ORDINAL_POSITION"
	)

	with MSSQLDatabase(server_document) as database:
		rows = database.sql(query, [table_name], as_dict=True)

	schema = {}
	for row in rows:
		schema[row["COLUMN_NAME"]] = {
			"sql_type": row["DATA_TYPE"],
			"length": row["CHARACTER_MAXIMUM_LENGTH"],
			"nullable": row["IS_NULLABLE"] == "YES",
		}
	return schema


def format_schema_table(schema):
	"""Render an introspected schema as a fixed-width text table for CLI output."""
	if not schema:
		return "(no columns found — check the table name)"

	header = f"{'Column':<40} {'Type':<16} {'Length':<8} Nullable"
	separator = "-" * len(header)
	lines = [header, separator]
	for column_name, info in schema.items():
		length = "" if info["length"] is None else str(info["length"])
		nullable = "YES" if info["nullable"] else "NO"
		lines.append(f"{column_name:<40} {info['sql_type']:<16} {length:<8} {nullable}")
	return "\n".join(lines)


def suggest_schema_config(schema, table_name, primary_key_column=None):
	"""Produce a starter SCHEMA_CONFIG dict from an introspected schema, in the field config
	format documented in schema_config.py.

	Column names are emitted bare — the framework qualifies them with the table and
	bracket-quotes them — and the `table` key is omitted entirely, since every suggested
	field is on the introspected primary table and so takes the TABLE_NAME default. A
	developer editing this scaffold adds `table` only when repointing a field at a joined
	table.

	When primary_key_column is given, it is emitted once as the 'name' entry rather than also
	under its own snake_case fieldname: the two would be duplicate mappings of one column, and
	the framework already projects 'name' from it. Declare a separate mirrored id field by hand
	if the primary key should also appear on the form.

	Columns whose value cannot change for a given record are suggested as 'cache' for the
	developer to confirm — nothing reads that flag yet, but it is easier to review here than
	to add later.
	"""
	config = {}

	if primary_key_column:
		config["name"] = {"column": _strip_quoting(primary_key_column), "cache": True}

	for column_name, info in schema.items():
		if primary_key_column and column_name.lower() == primary_key_column.strip().strip("[]").lower():
			continue
		field_config = {"column": column_name}
		if _is_probably_cacheable(column_name):
			field_config["cache"] = True
		config[_columnname_to_fieldname(column_name)] = field_config

	return config


def _strip_quoting(column_name):
	"""Remove any bracket-quoting from a column name supplied on the command line."""
	return column_name.strip().strip("[]")


"""Columns whose value is fixed once a record is created, so the suggested config marks them
'cache' for the developer to confirm. Deliberately an exact-match list rather than an '*ID'
suffix rule: a foreign key like TopicID or ModifierID is an id but changes freely."""
CACHEABLE_COLUMN_NAMES = ("id", "datecreated", "creatorid")


def _is_probably_cacheable(column_name):
	"""Guess whether a column's value is fixed for the life of a record — its own identity
	column and creation stamps. A suggestion only; the developer confirms it."""
	return column_name.lower() in CACHEABLE_COLUMN_NAMES


def introspect_join_schemas(server_document, join_config):
	"""Introspect all tables referenced in a JOIN_CONFIG and return a merged column dict.

	`join_config` is the same list of JOIN descriptor dicts used by `JOIN_CONFIG` on
	a virtual DocType controller. Each entry's `"table"` key names a SQL Server table
	to introspect. Returns a merged dict of `{column_name: info}` across all joined
	tables, in the same shape as `introspect_table_schema`.

	Pass the result as `additional_discovered_columns` to `validate_schema_config`
	to enable column-existence checking for qualified `sql_column` references
	(e.g. `"Categories.Topic"`).
	"""
	merged = {}
	for join_entry in (join_config or []):
		table = join_entry["table"]
		merged.update(introspect_table_schema(server_document, table))
	return merged


"""Ascend columns that must map to specific Frappe standard fieldnames rather
than their generic snake_case conversion, so edits to the Virtual DocType
resolve correctly."""
COLUMN_TO_FIELDNAME_OVERRIDES = {
	"datemodified": "modified",
	"modifierid": "modified_by",
}


def _columnname_to_fieldname(column_name):
	"""Convert a SQL column name (e.g. "Store UPC", "MfgrPartNo") to a snake_case fieldname."""
	import re

	override = COLUMN_TO_FIELDNAME_OVERRIDES.get(column_name.lower())
	if override:
		return override

	# Insert underscores at camelCase boundaries, then normalize separators.
	spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", column_name)
	return re.sub(r"[^0-9a-zA-Z]+", "_", spaced).strip("_").lower()


def _sql_type_to_fieldtype(sql_type):
	"""Map a SQL Server data type to a reasonable default Frappe fieldtype."""
	sql_type = sql_type.lower()
	if sql_type in ("int", "bigint", "smallint", "tinyint"):
		return "Int"
	if sql_type in ("decimal", "numeric", "money", "smallmoney", "float", "real"):
		return "Currency"
	if sql_type in ("bit",):
		return "Check"
	if sql_type in ("date", "datetime", "datetime2", "smalldatetime"):
		return "Datetime"
	return "Data"
