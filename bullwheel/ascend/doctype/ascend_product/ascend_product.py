# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Ascend Product virtual DocType — reference implementation of the framework.

This controller demonstrates the Virtual DocType framework: it declares only
TABLE_NAME, JOIN_CONFIG and SCHEMA_CONFIG, and inherits all query logic
(load_from_db, get_list, get_count, get_values, ordering, write guards) from
AbstractVirtualDocType. SCHEMA_CONFIG is the single source of truth — the SELECT
projection, WHERE/ORDER BY column resolution, the alternate-name widening, and the
linked-id pairing used on save are all derived from it.

See documentation/VIRTUAL_DOCTYPE_DEVELOPMENT.md for the full workflow, and
bullwheel/ascend/schema_config.py for every field config option.
"""

import json
import frappe

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class AscendProduct(AbstractVirtualDocType):
	"""Virtual DocType mapping the Ascend RMS `Products` table."""

	TABLE_NAME = "Products"
	ALLOW_WRITE = True

	# Products.NonInventory is a flag this DocType surfaces no field for, so nothing on the
	# document ever supplies it and db_insert left it at the column default — NULL, since that
	# column has none. Ascend reads a NULL flag as neither set nor unset and drops the row
	# wherever it filters on one: every product created with NonInventory NULL is missing from
	# the item grid of any purchase order referencing it, while the order header still counts
	# and totals it. Measured on PO "Bearded Ginger Helm of Sun Valley Batch 1" — 223 of 243
	# lines had NonInventory NULL, and the grid rendered every one of the 20 rows that had it
	# set and none of the rest.
	#
	# Hide is deliberately absent: it came back non-NULL on all 243, so that column carries its
	# own database default and needs nothing from us. Reconciled, NoLabel, eCommerce, DolCom,
	# PrintLabelsByDivision and HasPendingDelta are equally undeclared and so equally unwritten,
	# but whether Ascend needs them non-NULL has not been checked — add them here only once a
	# NULL count on the Products table says they matter.
	INSERT_DEFAULTS = {
		'non_inventory': 0,
	}

	# 'category' displays the joined column cat.Topic, which can't be written directly. Its
	# foreign key lives on Products as TopicID (mapped to 'category_id'). On save the framework
	# resolves the chosen category (a Product Category name) to its Categories.ID via the linked
	# DocType's database_id field and writes it to category_id -> Products.TopicID.
	#
	# 'upc' is marked alternate_name, so a product can be loaded and Link-resolved by UPC in
	# addition to its Store SKU primary key.
	SCHEMA_CONFIG = {
		'name':                      {'column': 'Store UPC', 'cache': False},
		'id':                        {'column': 'ID', 'cache': True},
		'category':                  {'table': 'cat', 'column': 'Topic',
		                              'linked_id': {'id_field': 'category_id',
		                                            'link_doctype': 'Product Category',
		                                            'link_id_field': 'database_id'}},
		'category_id':               {'column': 'TopicID'},
		'description':               {'column': 'Description'},
		'price':                     {'column': 'Price'},
		'estimated_cost':            {'column': 'EstCost'},
		'quantity':                  {'column': 'Quantity'},
		'reorder_level':             {'column': 'ReorderLevel'},
		'maximum':                   {'column': 'Maximum'},
		'commission':                {'column': 'Commission'},
		'upc':                       {'column': 'UPC', 'alternate_name': True},
		'manufacturers_part_number': {'column': 'MfgrPartNo'},
		'reconciled':                {'column': 'Reconciled'},
		'store_sku':                 {'column': 'Store UPC'},
		'keyword':                   {'column': 'Keyword'},
		'location':                  {'column': 'Location'},
		'brand':                     {'column': 'Brand'},
		'color':                     {'column': 'Color'},
		'size':                      {'column': 'Size'},
		'other':                     {'column': 'Other'},
		'division':                  {'column': 'Division'},
		'e_commerce':                {'column': 'eCommerce'},
		'min2':                      {'column': 'Min2'},
		'max2':                      {'column': 'Max2'},
		'no_label':                  {'column': 'NoLabel'},
		'non_inventory':             {'column': 'NonInventory'},
		'appt_length':               {'column': 'ApptLength'},
		'creator_id':                {'column': 'CreatorID', 'cache': True},
		'modified_by':               {'column': 'ModifierID'},
		'date_created':              {'column': 'DateCreated', 'cache': True},
		'modified':                  {'column': 'DateModified'},
		'hide':                      {'column': 'Hide'},
		'loc_from_id':               {'column': 'LocFromID'},
		'dol_com':                   {'column': 'DolCom'},
		'average_cost':              {'column': 'AvgCost'},
		'comments':                  {'column': 'Comments'},
		'date_qty_chng':             {'column': 'DateQtyChng'},
		'print_labels_by_division':  {'column': 'PrintLabelsByDivision'},
		'row_version':               {'column': 'Row_Version'},
		'date_reconciled':           {'column': 'DateReconciled'},
		'modifier_location_id':      {'column': 'ModifierLocationID'},
		'last_cost':                 {'column': 'LastCost'},
		'concurrency_token':         {'column': 'ConcurrencyToken'},
		'has_pending_delta':         {'column': 'HasPendingDelta'},
		'style_name':                {'column': 'StyleName'},
		'style_number':              {'column': 'StyleNumber'},
		'season':                    {'column': 'Season'},
		'year':                      {'column': 'Year'},
		'gender':                    {'column': 'Gender'},
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