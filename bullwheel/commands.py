# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Bullwheel bench CLI commands.

Frappe discovers the `commands` list below by importing `bullwheel.commands`,
making each command available as `bench <command>`.
"""

import click
import frappe
from frappe.commands import get_site, pass_context
from frappe.exceptions import SiteNotSpecifiedError


@click.command("introspect-schema")
@click.option("--table", "table_name", required=True, help="SQL Server table name to introspect, e.g. Products.")
@click.option(
	"--server",
	"server_name",
	default=None,
	help="SQL Server DocType record name. Defaults to Bullwheel Settings -> default_database.",
)
@click.option("--suggest", is_flag=True, default=False, help="Also print a starter SCHEMA_CONFIG dict.")
@click.option(
	"--primary-key",
	"primary_key_column",
	default=None,
	help="Primary key column name (e.g. ID). Used with --suggest to generate the required 'name' entry.",
)
@click.option(
	"--join-table",
	"join_tables",
	multiple=True,
	help="Additional table to introspect for JOIN configs. Repeatable: --join-table Categories --join-table Vendors.",
)
@pass_context
def introspect_schema(context, table_name, server_name=None, suggest=False, primary_key_column=None, join_tables=()):
	"""Discover the columns of an Ascend SQL Server table.

	Queries INFORMATION_SCHEMA.COLUMNS for the given table and prints a table of
	column names, types, lengths, and nullability. With --suggest, also prints a
	scaffold SCHEMA_CONFIG. Pass --primary-key to include the required 'name' entry
	in the suggested config. Use --join-table to also print columns from joined tables
	when writing a SCHEMA_CONFIG for a DocType that uses JOIN_CONFIG.
	"""
	from bullwheel.ascend.virtual_doctype_base import get_default_ascend_database
	from bullwheel.ascend.schema_introspection import (
		format_schema_table,
		introspect_table_schema,
		suggest_schema_config,
	)

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	try:
		server_document = (
			frappe.get_doc("SQL Server", server_name) if server_name else get_default_ascend_database()
		)
		schema = introspect_table_schema(server_document, table_name)

		click.echo(f"\nTable '{table_name}' on server '{server_document.name}' — {len(schema)} columns\n")
		click.echo(format_schema_table(schema))

		for join_table in join_tables:
			join_schema = introspect_table_schema(server_document, join_table)
			click.echo(f"\nJoined table '{join_table}' — {len(join_schema)} columns\n")
			click.echo(format_schema_table(join_schema))

		if suggest and schema:
			click.echo("\n# Starter SCHEMA_CONFIG — review and edit before use:\n")
			if not primary_key_column:
				click.echo(
					"# NOTE: No --primary-key given. Add a 'name' entry manually pointing to\n"
					"# the primary key column before using this config, e.g.:\n"
					"#   'name': {'column': 'ID', 'cache': True},\n"
					"# Columns from a joined table also need a 'table' key naming the JOIN_CONFIG\n"
					"# alias; everything else defaults to TABLE_NAME. See ascend/schema_config.py.\n"
				)
			click.echo(_format_suggested_config(suggest_schema_config(schema, table_name, primary_key_column)))
	finally:
		frappe.destroy()

	if not site:
		raise SiteNotSpecifiedError


def _format_suggested_config(config):
	"""Pretty-print a suggested SCHEMA_CONFIG dict as copy-pasteable Python source, aligning the
	field configs so the output reads like the hand-written configs it scaffolds."""
	if not config:
		return "SCHEMA_CONFIG = {}"

	# Widest quoted fieldname plus its colon, so every field config starts at the same column.
	key_width = max(len(fieldname) for fieldname in config) + 4
	lines = []
	for fieldname, field_config in config.items():
		options = ", ".join(f"'{key}': {value!r}" for key, value in field_config.items())
		quoted_key = f"'{fieldname}':"
		lines.append(f"\t{quoted_key:<{key_width}}{{{options}}}")
	return "SCHEMA_CONFIG = {\n" + ",\n".join(lines) + "\n}"


@click.command("backfill-insert-defaults")
@click.option(
	"--doctype",
	"doctype_name",
	default="Ascend Product",
	help="Virtual DocType whose INSERT_DEFAULTS to backfill. Defaults to Ascend Product.",
)
@click.option(
	"--server",
	"server_name",
	default=None,
	help="SQL Server DocType record name. Defaults to Bullwheel Settings -> default_database.",
)
@click.option("--apply", "apply_changes", is_flag=True, default=False, help="Perform the UPDATE. Without this, only counts are reported.")
@pass_context
def backfill_insert_defaults(context, doctype_name="Ascend Product", server_name=None, apply_changes=False):
	"""Set a virtual DocType's INSERT_DEFAULTS on existing Ascend rows that are still NULL.

	INSERT_DEFAULTS only governs rows written from here on; rows created before a default was
	declared keep whatever the column defaulted to. This backfills those, one UPDATE per
	declared field, touching only rows where the column IS NULL — a row that already carries a
	value (including a deliberate non-default one) is never rewritten.

	Reports the affected row count per column and does nothing else unless --apply is passed,
	so the scope of the change can be read before any row in Ascend is modified.
	"""
	from frappe.model.base_document import get_controller

	from bullwheel.ascend.schema_config import quote_column
	from bullwheel.ascend.virtual_doctype_base import get_default_ascend_database
	from bullwheel.database.SQLServer import MSSQLDatabase

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	try:
		controller = get_controller(doctype_name)
		insert_defaults = controller.INSERT_DEFAULTS
		if not insert_defaults:
			click.echo(f"{doctype_name} declares no INSERT_DEFAULTS — nothing to backfill.")
			return

		server_document = (
			frappe.get_doc("SQL Server", server_name) if server_name else get_default_ascend_database()
		)

		click.echo(
			f"\n{doctype_name} -> {controller.TABLE_NAME} on '{server_document.name}'"
			f" ({'APPLYING' if apply_changes else 'dry run — pass --apply to write'})\n"
		)

		with MSSQLDatabase(server_document) as ascend:
			for field, default in insert_defaults.items():
				# A callable default (e.g. a Bullwheel Settings lookup, a timestamp) is resolved
				# once here — the same value is used for every row this backfill pass touches,
				# same as db_insert resolves it once per document.
				value = default() if callable(default) else default
				if value is None:
					click.echo(f"  {field:<28} {'':<28} {'skipped':>8} — default resolved to None")
					continue

				# Resolved through the controller so the column is the same one db_insert would
				# write, bracket-quoted by the same helper rather than interpolated by hand.
				column = quote_column(controller._field_config(field)['column'])
				table = controller.TABLE_NAME

				pending = ascend.sql(
					f"SELECT COUNT(*) AS pending FROM {table} WHERE {column} IS NULL",
					[], as_dict=True,
				)[0]["pending"]

				if not apply_changes:
					click.echo(f"  {field:<28} {column:<28} {pending:>8} row(s) NULL -> would set {value!r}")
					continue

				ascend.sql(
					f"UPDATE {table} SET {column} = %s WHERE {column} IS NULL",
					[value], as_dict=False,
				)
				click.echo(f"  {field:<28} {column:<28} {ascend.cursor.rowcount:>8} row(s) set to {value!r}")

			if apply_changes:
				ascend.commit()
				click.echo("\nCommitted.")
	finally:
		frappe.destroy()

	if not site:
		raise SiteNotSpecifiedError


commands = [introspect_schema, backfill_insert_defaults]