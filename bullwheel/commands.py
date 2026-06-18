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
	"--join-table",
	"join_tables",
	multiple=True,
	help="Additional table to introspect for JOIN configs. Repeatable: --join-table Categories --join-table Vendors.",
)
@pass_context
def introspect_schema(context, table_name, server_name=None, suggest=False, join_tables=()):
	"""Discover the columns of an Ascend SQL Server table.

	Queries INFORMATION_SCHEMA.COLUMNS for the given table and prints a table of
	column names, types, lengths, and nullability. With --suggest, also prints a
	scaffold SCHEMA_CONFIG. Use --join-table to also print columns from joined tables
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
			click.echo(_format_suggested_config(suggest_schema_config(schema)))
	finally:
		frappe.destroy()

	if not site:
		raise SiteNotSpecifiedError


def _format_suggested_config(config):
	"""Pretty-print a suggested SCHEMA_CONFIG dict as copy-pasteable Python source."""
	lines = ["SCHEMA_CONFIG = {"]
	for fieldname, entry in config.items():
		display = "None" if entry["display"] is None else f'"{entry["display"]}"'
		lines.append(f'\t"{fieldname}": {{')
		lines.append(f'\t\t"sql_column": "{entry["sql_column"]}",')
		lines.append(f'\t\t"fieldtype": "{entry["fieldtype"]}",')
		lines.append(f'\t\t"display": {display},')
		lines.append(f'\t\t"searchable": {entry["searchable"]},')
		lines.append("\t},")
	lines.append("}")
	return "\n".join(lines)


commands = [introspect_schema]