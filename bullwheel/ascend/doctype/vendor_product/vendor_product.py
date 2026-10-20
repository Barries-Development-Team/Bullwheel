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


def _pending_new_product_uses_vpn(vendor, candidate, exclude_new_product=None) -> bool:
	"""True when a non-cancelled New Product for this vendor already holds `candidate` as its
	VPN. A New Product waits in Bullwheel until it is imported, so its VPN is not yet in
	VendorProducts and the Ascend check alone cannot see it."""
	filters = {"vendor": vendor, "vpn": candidate, "status": ["!=", "Cancelled"]}
	if exclude_new_product:
		filters["name"] = ["!=", exclude_new_product]
	return bool(frappe.db.exists("New Product", filters))


PART_NUMBER_LIMIT = 23  # Inclusive bound. 23 characters is the max that fit on a 2in, 300dpi Swap Tag. Limit in the Ascend database is 50.

# VPN layout:  PREFIX-BRANDMODELCOLORSIZE-COUNTER   e.g.  BAR-SWITCRENEGABLAMED-1
# Dashes only mark the boundaries of the prefix and the counter. The body components are run together.
SEGMENT_SEPARATOR = '-'
BODY_ORDER = ('brand', 'model', 'color', 'size')  # Order of the components inside the body.

# Minimum characters each component is guaranteed when the VPN has to be shortened.
# A component is never truncated below its minimum (or below its own length if it was already shorter).
# The counter is never truncated, since that would break uniqueness; its minimum only reserves space.
VPN_MINIMUMS = {
	'vpn_prefix': 2,
	'brand': 3,
	'model': 4,
	'color': 2,
	'size': 2,
	'counter': 1,
}

_COMPONENTS = ('vpn_prefix',) + BODY_ORDER + ('counter',)


def _validate_vpn_minimums():
	if set(VPN_MINIMUMS) != set(_COMPONENTS):
		raise ValueError(f'VPN_MINIMUMS keys must be exactly {_COMPONENTS}, got {tuple(VPN_MINIMUMS)}.')
	invalid = {name: value for name, value in VPN_MINIMUMS.items() if not isinstance(value, int) or value < 1}
	if invalid:
		raise ValueError(f'VPN_MINIMUMS values must be integers >= 1, got {invalid}.')
	# Worst case: every component present, so both segment separators are used.
	required = sum(VPN_MINIMUMS.values()) + 2 * len(SEGMENT_SEPARATOR)
	if required > PART_NUMBER_LIMIT:
		raise ValueError(
			f'Sum of VPN_MINIMUMS ({sum(VPN_MINIMUMS.values())}) plus separators ({2 * len(SEGMENT_SEPARATOR)}) '
			f'= {required} exceeds PART_NUMBER_LIMIT ({PART_NUMBER_LIMIT}).'
		)


_validate_vpn_minimums()  # Fail fast on a bad configuration.


def _normalize_component(value) -> str:
	"""Drop anything that isn't alphanumeric or whitespace, put each word in proper case, then join
	the words with no separator. Input case is irrelevant: 'JP 5' / 'jp 5' -> 'Jp5',
	'BLACK diamond' -> 'BlackDiamond'. None -> ''."""
	if value is None:
		return ''
	cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', str(value))
	return ''.join(word.capitalize() for word in cleaned.split())


def _normalize_prefix(value) -> str:
	"""The prefix is a vendor acronym, so it stays uppercase (BAR) instead of proper case."""
	return _normalize_component(value).upper()


def _assemble(components: dict) -> str:
	body = ''.join(components.get(name, '') for name in BODY_ORDER)
	segments = [components.get('vpn_prefix', ''), body, components['counter']]
	return SEGMENT_SEPARATOR.join(segment for segment in segments if segment)


def _build_vpn(parts: dict, counter: int) -> str:
	"""
	Assemble PREFIX-BODY-COUNTER, shortening components if the result is over PART_NUMBER_LIMIT.

	Each pass removes one character from the component with the highest weight, where
	weight = current length / minimum length, until the VPN fits. Components at or below their
	minimum are not eligible, and the counter is never eligible.
	"""
	components = {name: parts[name] for name in ('vpn_prefix',) + BODY_ORDER if parts.get(name)}
	components['counter'] = str(counter)

	while len(_assemble(components)) > PART_NUMBER_LIMIT:
		candidates = [
			name for name in components
			if name != 'counter' and len(components[name]) > VPN_MINIMUMS[name]
		]
		if not candidates:
			raise ValueError(
				f'Cannot fit "{_assemble(components)}" within {PART_NUMBER_LIMIT} characters '
				f'without truncating a component below its minimum.'
			)
		# max() returns the first of any tied candidates, so ties favor the earlier component.
		target = max(candidates, key=lambda name: len(components[name]) / VPN_MINIMUMS[name])
		components[target] = components[target][:-1]

	return _assemble(components)


@frappe.whitelist()
def generate_vpn(vendor_id, vpn_prefix, brand, model, size=None, color=None, vendor=None, exclude_new_product=None) -> str:
	"""Build a unique Ascend part number as PREFIX-BRANDMODELCOLORSIZE-COUNTER (e.g. BAR-SWITCRENEGABLAMED-1).
	Each component is stripped of non-alphanumeric characters, put in proper case and has its whitespace
	removed (the prefix stays uppercase); brand is capped to its first two words. If the
	result would exceed PART_NUMBER_LIMIT, components are shortened one character at a time, always
	the one with the highest (current length / minimum length), never below VPN_MINIMUMS. A counter
	(1, 2, …) is then searched for, inside one Ascend connection, until no VendorProducts row matches."""
	limited_brand = ' '.join(str(brand).strip().split()[:2])  # Keep the existing two-word brand limit.
	parts = {
		'vpn_prefix': _normalize_prefix(vpn_prefix),
		'brand': _normalize_component(limited_brand),
		'model': _normalize_component(model),
		'color': _normalize_component(color),
		'size': _normalize_component(size),
	}

	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		counter = 1
		while True:
			try:
				candidate = _build_vpn(parts, counter)
			except ValueError as error:
				frappe.throw(str(error))
			if not _part_number_match_count(ascend, vendor_id, candidate):
				return candidate
			counter += 1