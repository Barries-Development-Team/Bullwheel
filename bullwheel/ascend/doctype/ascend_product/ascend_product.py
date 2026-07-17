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

import json
import frappe

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class AscendProduct(AbstractVirtualDocType):
	"""Virtual DocType mapping the Ascend RMS `Products` table."""

	TABLE_NAME = "Products"
	ALLOW_WRITE = True
	ALT_NAME_RESOLUTION_FIELDS = ['upc']

	SCHEMA_CONFIG = {
		'name': 'Products.[Store UPC]',
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
		'manufacturers_part_number': 'Products.MfgrPartNo',
		'reconciled': 'Products.Reconciled',
		'store_sku': 'Products.[Store UPC]',
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
		'modified_by': 'modifier.Initials',
		'date_created': 'Products.DateCreated',
		'modified': 'Products.DateModified',
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
		},
		{
			"join":  "LEFT JOIN",
			"table": "Users",
			"alias": "modifier", # Can't use "user" since it's a reserved keyword.
			"on":    "Products.ModifierID = modifier.ID",
		}
	]

	# Swap and Online price display fields are virtual and not stored in the Ascend database,
	# so we need to fetch them from the Product Price DocType.

	@property
	def swap_price(self):
		return frappe.db.get_value('Product Price', f'PRICE-SWAP-{self.name}', 'price')

	@property
	def online_price(self):
		return frappe.db.get_value('Product Price', f'PRICE-ONLINE-{self.name}', 'price')


@frappe.whitelist()
def get_values(name: str, fields) -> frappe._dict | None:
	"""Helper function to call the get_values method of AscendProduct class."""
	if type(fields) is str:
		fields = json.loads(fields)
	return AscendProduct.get_values(name, fields)