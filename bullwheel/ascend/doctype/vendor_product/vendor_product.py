# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import re

import frappe

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType
from bullwheel.bullwheel_core import get_default_ascend_database
from bullwheel.database.SQLServer import MSSQLDatabase


class VendorProduct(AbstractVirtualDocType):
	LABEL_RESOLUTION_FIELD = 'product'  # Link → Ascend Product; label prints resolve through it (see label_printing/resolution.py)
	TABLE_NAME = "VendorProducts"     # Ascend SQL table name
	NAME_EXPRESSION = "CONCAT(VendorProducts.PartNumber, ' (', Vendor.Name, ')')"  # Optional SQL expression to generate the 'name' field for the virtual doctype.
	# No 'name' entry — NAME_EXPRESSION supplies the primary key. Fields sourced from the two
	# joined tables name their alias; everything else defaults to TABLE_NAME.
	SCHEMA_CONFIG = {
		'id':                   {'column': 'ID', 'cache': True},
		'vendor_id':            {'column': 'VendorID'},
		'vendor':               {'table': 'Vendor', 'column': 'Name'},
		'product_id':           {'column': 'ProductID'},
		'product':              {'table': 'Product', 'column': 'Store UPC'},
		'upc':                  {'table': 'Product', 'column': 'UPC'},
		'description':          {'column': 'Description'},
		'part_number':          {'column': 'PartNumber'},
		'cost':                 {'column': 'Cost'},
		'creator_id':           {'column': 'CreatorID', 'cache': True},
		'modifier_id':          {'column': 'ModifierID'},
		'date_created':         {'column': 'DateCreated', 'cache': True},
		'date_modified':        {'column': 'DateModified'},
		'hide':                 {'column': 'Hide'},
		'loc_from_id':          {'column': 'LocFromID'},
		'row_version':          {'column': 'Row_Version'},
		'case_quantity':        {'column': 'CaseQty'},
		'case_upc':             {'column': 'CaseUPC'},
		'case_msrp':            {'column': 'CaseMSRP'},
		'modifier_location_id': {'column': 'ModifierLocationID'},
		'concurrency_token':    {'column': 'ConcurrencyToken'},
		'has_pending_delta':    {'column': 'HasPendingDelta'},
	}
	JOIN_CONFIG = [
    {
        "join":  "INNER JOIN",                          # JOIN type
        "table": "Vendors",                         # Table to join
        "alias": "Vendor",                                # Optional alias
        "on":    "VendorProducts.VendorID = Vendor.ID",          # Full ON condition
    },
	{
        "join":  "INNER JOIN",                          # JOIN type
        "table": "Products",                         # Table to join
        "alias": "Product",                                # Optional alias
        "on":    "VendorProducts.ProductID = Product.ID",          # Full ON condition
    }
	]

def _part_number_match_count(ascend, vendor_id, part_number, part_number_similarity: str = 'equals') -> int:
	"""Count VendorProducts rows for this vendor matching part_number, either exactly or via a
	wildcard LIKE depending on part_number_similarity. Runs on an already-open ascend connection
	so callers that need several checks in a row (e.g. a counter-suffix search) share one
	connection instead of opening a new one per check."""

	match part_number_similarity:
		case 'equals':
			query = "SELECT ID FROM VendorProducts WHERE VendorID = %s AND PartNumber = %s"
			values = [vendor_id, part_number]
		case 'like':
			query = "SELECT ID FROM VendorProducts WHERE VendorID = %s AND PartNumber LIKE %s"
			values = [vendor_id, f'%{part_number}%']

	existing = ascend.sql(query=query, values=values, as_dict=True)
	return len(existing)


@frappe.whitelist()
def vendor_product_match_count(vendor_id, part_number, part_number_similarity: str = 'equals') -> int:
	"""Check whether a VendorProducts row already exists for this vendor, matching part_number
	either exactly or via a wildcard LIKE depending on part_number_similarity. Returns the
	number of matching rows."""

	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		return _part_number_match_count(ascend, vendor_id, part_number, part_number_similarity)


def _format_vpn_component(value) -> str:
	"""Normalize one VPN component: strip anything that isn't alphanumeric or whitespace,
	collapse remaining whitespace to a single "-", then uppercase."""

	value = re.sub(r'[^a-zA-Z0-9\s]', '', str(value).strip())
	return re.sub(r'\s+', '-', value).upper()


PART_NUMBER_LIMIT = 45  # Ascend's Part Number column allows 50 characters; kept as a safety margin.


@frappe.whitelist()
def generate_vpn(vendor_id, vpn_prefix, brand, model, size=None, color=None) -> str:
	"""Build a unique Ascend part number as Vendor Acronym-Brand-Model-Size-Color-Counter: brand
	is capped to its first two words and model is truncated if needed to stay within
	PART_NUMBER_LIMIT, then a counter suffix (-1, -2, …) is searched for, inside one Ascend
	connection, until a part number with no existing VendorProducts match is found."""

	def build_base_vpn(model_value):
		components = [vpn_prefix, limited_brand, model_value, size, color]
		formatted = [_format_vpn_component(component) for component in components if component is not None and str(component).strip() != '']
		return '-'.join(formatted)

	limited_brand = ' '.join(brand.strip().split()[:2])
	base_vpn = build_base_vpn(model)

	# Still over the limit: shorten "model" by exactly the overage rather than a fixed amount,
	# so short overages cost as little of "model" as possible.
	if len(base_vpn) > PART_NUMBER_LIMIT:
		overage = len(base_vpn) - PART_NUMBER_LIMIT
		formatted_model = _format_vpn_component(model)
		truncated_model = formatted_model[:max(0, len(formatted_model) - overage)]
		base_vpn = build_base_vpn(truncated_model)

	if len(base_vpn) > PART_NUMBER_LIMIT:
		frappe.throw(f'Generated VPN "{base_vpn}" exceeds the {PART_NUMBER_LIMIT}-character limit even after truncating "model".')

	counter = 1
	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		while True:
			candidate = f"{base_vpn}-{counter}"
			if not _part_number_match_count(ascend, vendor_id, candidate):
				return candidate
			counter += 1

def create_vendor_product(
	vendor_id, product_id, part_number, cost, description=None,
	case_quantity=None, case_upc=None, case_msrp=None,
):
	"""Insert one VendorProducts row into Ascend, linking a Product to a vendor that doesn't yet
	carry it. Used by Order Receipt's vendor-link flow during receiving and by New Product's
	insert for brand-new products. Returns True when a row was inserted, False when an existing
	row was found and reused."""

	
	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		if _part_number_match_count(ascend, vendor_id, part_number):
			return False

		# Raw parameterized INSERT instead of the virtual doctype framework: NAME_EXPRESSION
		# (PartNumber + Vendor.Name) isn't a real column, so the framework's generic db_insert
		# can't produce it.
		ascend.sql(
			"INSERT INTO VendorProducts "
			"(ID, VendorID, ProductID, PartNumber, Cost, Description, CaseQty, CaseUPC, CaseMSRP, "
			"DateCreated, Hide, HasPendingDelta) "
			"VALUES (NEWID(), %s, %s, %s, %s, %s, %s, %s, %s, GETDATE(), 0, 0)",
			[vendor_id, product_id, part_number, cost, description, case_quantity, case_upc, case_msrp],
			as_dict=False,
		)

		inserted_row_count = ascend.cursor.rowcount
		if inserted_row_count != 1:
			frappe.throw(f"Insert into VendorProducts affected {inserted_row_count} rows instead of exactly one.")

		return True