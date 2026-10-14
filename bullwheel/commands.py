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


@click.command("audit-bullwheel-products")
@click.option(
	"--output",
	"output_path",
	default=None,
	type=click.Path(dir_okay=False, writable=True),
	help="CSV file to write. Defaults to printing the CSV to the terminal.",
)
@pass_context
def audit_bullwheel_products(context, output_path=None):
	"""List Ascend Products that Bullwheel created before it stopped writing to Ascend, and what
	is missing on them.

	Until now creating a New Product also inserted its Ascend Product directly, bypassing the
	validation Ascend runs when a product is created in Ascend itself. This report reads those
	products back (read-only, through the Ascend Product and Vendor Product DocTypes) and flags the
	ones whose ModifierLocationID, ConcurrencyToken or NonInventory is NULL, or that have no Vendor
	Product, so staff can open and re-save them in Ascend to repair them.
	"""
	import csv
	import sys

	from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	try:
		# Products Bullwheel inserted itself are the Imported New Products that were never exported
		# on an import sheet (the migration patch marked them Imported without an export date).
		store_skus = frappe.get_all(
			"New Product", filters={"status": "Imported", "exported_on": ["is", "not set"]}, pluck="name"
		)
		products = AscendProduct.get_bulk_values(
			store_skus,
			["description", "creator_id", "date_created", "modifier_location_id", "concurrency_token", "non_inventory"],
		)

		vendor_product_skus = set()
		sku_list = list(products)
		for start in range(0, len(sku_list), 500):
			chunk = sku_list[start:start + 500]
			vendor_product_skus.update(
				frappe.get_all(
					"Vendor Product", filters={"product": ["in", chunk]}, pluck="product", limit_page_length=0
				)
			)

		rows = []
		for store_sku, product in products.items():
			missing = [
				column for column, field in (
					("ModifierLocationID", "modifier_location_id"),
					("ConcurrencyToken", "concurrency_token"),
					("NonInventory", "non_inventory"),
				) if product.get(field) is None
			]
			if store_sku not in vendor_product_skus:
				missing.append("Vendor Product")
			if missing:
				rows.append([store_sku, product.description, product.date_created, "; ".join(missing)])

		stream = open(output_path, "w", newline="") if output_path else sys.stdout
		try:
			writer = csv.writer(stream)
			writer.writerow(["Store SKU", "Description", "Created", "Missing"])
			writer.writerows(rows)
		finally:
			if output_path:
				stream.close()

		click.echo(
			f"{len(rows)} of {len(products)} Bullwheel-created product(s) need repair in Ascend."
			+ (f" Written to {output_path}." if output_path else ""),
			err=True,
		)
	finally:
		frappe.destroy()

	if not site:
		raise SiteNotSpecifiedError


commands = [introspect_schema, audit_bullwheel_products]
