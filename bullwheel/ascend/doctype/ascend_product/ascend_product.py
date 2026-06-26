# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Ascend Product virtual DocType — reference implementation of the framework.

This controller demonstrates the Virtual DocType framework: it declares only
TABLE_NAME and SCHEMA_CONFIG, and inherits all query logic
(load_from_db, get_list, get_count, ordering, read-only guards) from
AbstractVirtualDocType. SCHEMA_CONFIG is the single source of truth — the
FIELD_TO_COLUMN map, SELECT clause, search columns, and Link autocomplete hook
are all derived from it.

See bullwheel/ascend/VIRTUAL_DOCTYPE_DEVELOPMENT.md for the full workflow.
"""

import frappe
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType
from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database
from bullwheel.ascend.schema_config_builder import normalize_record


class AscendProduct(AbstractVirtualDocType):
	"""Read-only virtual DocType mapping the Ascend RMS `Products` table."""

	TABLE_NAME = "Products"

	SCHEMA_CONFIG = {
        'name': 'Products.ID',
        'id': 'Products.ID',
        'category': 'cat.Topic',
        'description': 'Products.Description',
        'price': 'Products.Price',
        'estimated_cost': 'Products.EstCost',
        'quantity': 'Products.Quantity',
        'reorder_level': 'Products.ReorderLevel',
        'maximum': 'Products.Maximum',
        'commission': 'Products.Commission',
        'upc': 'Products.UPC',
        'mfgr_part_no': 'Products.MfgrPartNo',
        'reconciled': 'Products.Reconciled',
        'store_upc': 'Products.[Store UPC]',
        'keyword': 'Products.Keyword',
        'location': 'Products.Location',
        'brand': 'Products.Brand',
        'color': 'Products.Color',
        'size': 'Products.Size',
        'other': 'Products.Other',
        'division': 'Products.Division',
        'e_commerce': 'Products.eCommerce',
        'min2': 'Products.Min2',
        'max2': 'Products.Max2',
        'no_label': 'Products.NoLabel',
        'non_inventory': 'Products.NonInventory',
        'appt_length': 'Products.ApptLength',
        'creator_id': 'Products.CreatorID',
        'modifier_id': 'Products.ModifierID',
        'date_created': 'Products.DateCreated',
        'date_modified': 'Products.DateModified',
        'hide': 'Products.Hide',
        'loc_from_id': 'Products.LocFromID',
        'dol_com': 'Products.DolCom',
        'average_cost': 'Products.AvgCost',
        'comments': 'Products.Comments',
        'date_qty_chng': 'Products.DateQtyChng',
        'print_labels_by_division': 'Products.PrintLabelsByDivision',
        'row_version': 'Products.Row_Version',
        'date_reconciled': 'Products.DateReconciled',
        'modifier_location_id': 'Products.ModifierLocationID',
        'last_cost': 'Products.LastCost',
        'concurrency_token': 'Products.ConcurrencyToken',
        'has_pending_delta': 'Products.HasPendingDelta',
        'style_name': 'Products.StyleName',
        'style_number': 'Products.StyleNumber',
        'season': 'Products.Season',
        'year': 'Products.Year',
        'gender': 'Products.Gender'
}

	JOIN_CONFIG = [
    {
        "join":  "LEFT JOIN",                          # JOIN type
        "table": "Categories",                         # Table to join
        "alias": "cat",                                # Optional alias
        "on":    "Products.TopicID = cat.ID",          # Full ON condition
    }
]

# Link-field autocomplete hook. Registered in hooks.py under standard_queries as
# bullwheel.ascend.doctype.ascend_product.ascend_product.ascend_product_search.
# Each result is (name, description).
# ascend_product_search = AscendProduct.make_search_function(display_fields=["description"])

@frappe.whitelist()
def get_product_dict(id: str, type: str = 'full') -> dict | None:
	"""Look up a single product by its Store UPC or UPC. Returns the product
	# record as a dict, or None when no matching product exists so callers can
	# distinguish "found" from "not found" without catching an exception.
	# Optionally, using 'type' you can select to return the full dict or just a summary.
	# the summary includes only the Description, Ascend SKU, and UPC."""

	if type == 'full':
		query = 'SELECT * FROM Products WHERE [Store UPC] = %s OR UPC = %s'
	elif type == 'summary':
		query = 'SELECT Description, [Store UPC], UPC FROM Products WHERE [Store UPC] = %s OR UPC = %s'
	else:
		raise ValueError("Type options are \'full\' and \'summary\'.")

	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		result = ascend.sql(
			query=query,
			values=(id, id),
			as_dict=True
		)
	if not result:
		return None
	return frappe._dict(normalize_record(result[0]))