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


def suggest_schema_config(schema, primary_key_column=None):
	"""Produce a starter SCHEMA_CONFIG dict from an introspected schema.

	Every column becomes a snake_case fieldname mapped back to its SQL column, with
	conservative defaults (display None, searchable False). It is a scaffold to
	copy into a controller and edit down — not a finished config. SQL columns whose
	names contain spaces are bracket-quoted so the SELECT clause is valid as-is.

	When `primary_key_column` is provided (e.g. `"ID"`), a `"name"` entry is
	prepended at the top of the config pointing to that column with display "hidden".
	Without it, no `"name"` entry is generated and the developer must add one
	manually before the config is valid.
	"""
	config = {}

	if primary_key_column:
		sql_column = f"[{primary_key_column}]" if " " in primary_key_column else primary_key_column
		pk_info = schema.get(primary_key_column, {})
		config["name"] = sql_column

	for column_name, info in schema.items():
		fieldname = _columnname_to_fieldname(column_name)
		sql_column = f"[{column_name}]" if " " in column_name else column_name
		config[fieldname] = sql_column

	return config


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


def _columnname_to_fieldname(column_name):
	"""Convert a SQL column name (e.g. "Store UPC", "MfgrPartNo") to a snake_case fieldname."""
	import re

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
