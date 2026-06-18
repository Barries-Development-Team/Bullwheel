# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Generator for Virtual DocType Link-field search hooks.

Frappe's default search_widget pipeline (`as_list` / relevance_sorter) is
incompatible with virtual DocType results, so each searchable virtual DocType
registers a custom function via the `standard_queries` hook in hooks.py. Rather
than hand-write that near-identical function for every DocType, call
``create_virtual_doctype_search`` and bind the result to a module-level name:

    ascend_product_search = create_virtual_doctype_search(
        table_name="Products",
        primary_key_column="ID",
        primary_key_field="ascend_database_id",
        select_clause=SELECT_CLAUSE,
        field_to_column=FIELD_TO_COLUMN,
        search_columns=SEARCH_COLUMNS,
        display_fields=["description", "store_sku"],
    )

Then register the dotted path in hooks.py:

    standard_queries = {
        "Ascend Product": "bullwheel.ascend.doctype.ascend_product.ascend_product.ascend_product_search",
    }
"""

import frappe

from bullwheel.ascend.AscendDatabase import AscendDatabase, get_default_ascend_database
from bullwheel.ascend.schema_config_builder import normalize_record


def create_virtual_doctype_search(
	table_name,
	primary_key_column,
	primary_key_field,
	select_clause,
	field_to_column,
	search_columns,
	display_fields,
):
	"""Build a whitelisted Link-field search function for a virtual DocType.

	The returned function matches Frappe's `standard_queries` contract and queries
	AscendDatabase directly, bypassing the search_widget pipeline. It returns
	`(name, *display_field_values)` tuples for autocomplete, or `frappe._dict`
	rows (with `name` populated) when called with `as_dict=True`.

	Arguments mirror the derived constants produced from a SCHEMA_CONFIG:
	    primary_key_column — SQL column name of the primary key (e.g. "ID")
	    primary_key_field  — Frappe fieldname holding that key (e.g. "ascend_database_id")
	    display_fields     — fieldnames shown after the id in autocomplete tuples
	"""

	@frappe.whitelist()
	def virtual_doctype_search(_doctype, txt, _searchfield, start, page_length, _filters, as_dict=False):
		# _doctype, _searchfield, _filters are required positional args from the
		# standard_queries contract but are not needed for the Ascend query.
		_ = _doctype, _searchfield, _filters

		with AscendDatabase(get_default_ascend_database()) as ascend:
			records = ascend.get_list(
				table_name,
				select_clause,
				primary_key_column,
				field_to_column,
				search_columns=search_columns,
				page_length=int(page_length),
				start=int(start),
				txt=txt,
			)

		records = [normalize_record(record) for record in records]

		if as_dict:
			return [frappe._dict({**record, "name": record[primary_key_field]}) for record in records]

		return [
			(record[primary_key_field], *(record.get(field) or "" for field in display_fields))
			for record in records
		]

	return virtual_doctype_search
