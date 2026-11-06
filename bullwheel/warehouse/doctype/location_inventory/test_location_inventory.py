# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for the bulk product-link check that replaces Frappe's per-row check on Location
Inventory rows (one Ascend load per row, on every save of the bay)."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.warehouse.doctype.location_inventory import location_inventory
from bullwheel.warehouse.doctype.location_inventory.location_inventory import (
	LocationInventory,
	find_invalid_inventory_products,
)

MODULE = location_inventory.__name__
UNSAVED = object()


def _row(product, product_type="Ascend Product", idx=1, saved=UNSAVED):
	"""A Location Inventory row stand-in. `saved` is the row as last saved: a (product,
	product_type) pair, or UNSAVED for a row added since."""
	row = SimpleNamespace(product=product, product_type=product_type, idx=idx)
	row._doc_before_save = None if saved is UNSAVED else SimpleNamespace(product=saved[0], product_type=saved[1])
	return row


class UnitTestFindInvalidInventoryProducts(UnitTestCase):

	def _check(self, rows, ascend_found=(), new_products_found=(), alternate_matches=None):
		"""Run the check with Ascend and Bullwheel lookups mocked. Returns (invalid links, the
		mocks) so tests can assert how many lookups ran."""
		alternate_matches = alternate_matches or {}
		with (
			patch(f"{MODULE}.AscendProduct.get_bulk_values", return_value={name: frappe._dict(name=name) for name in ascend_found}) as bulk,
			patch(f"{MODULE}.AscendProduct.find_by_identifier", side_effect=lambda identifier, fields: [frappe._dict(name=alternate_matches[identifier])] if identifier in alternate_matches else []) as single,
			patch(f"{MODULE}.frappe.get_all", return_value=list(new_products_found)) as get_all,
			patch(f"{MODULE}.frappe.get_meta", return_value=SimpleNamespace(get_label=lambda fieldname: "Product")),
		):
			invalid = find_invalid_inventory_products(rows)
		return invalid, SimpleNamespace(bulk=bulk, single=single, get_all=get_all)

	def test_whole_bay_is_one_ascend_query(self):
		"""The performance fix: 20 new rows cost one bulk query, not 20 document loads."""
		rows = [_row(f"SKU-{number}", idx=number) for number in range(20)]
		invalid, lookups = self._check(rows, ascend_found=[f"SKU-{number}" for number in range(20)])
		self.assertEqual(invalid, [])
		lookups.bulk.assert_called_once()
		lookups.single.assert_not_called()

	def test_unchanged_rows_are_not_rechecked(self):
		"""A check-in that bumps one quantity re-validates nothing."""
		rows = [_row(f"SKU-{number}", saved=(f"SKU-{number}", "Ascend Product")) for number in range(20)]
		invalid, lookups = self._check(rows)
		self.assertEqual(invalid, [])
		lookups.bulk.assert_not_called()
		lookups.get_all.assert_not_called()

	def test_changed_product_or_type_is_rechecked(self):
		rows = [
			_row("SKU-NEW", saved=("SKU-OLD", "Ascend Product")),
			_row("NP-00001", "New Product", idx=2, saved=("NP-00001", "Ascend Product")),
		]
		invalid, lookups = self._check(rows, ascend_found=["SKU-NEW"], new_products_found=["NP-00001"])
		self.assertEqual(invalid, [])
		lookups.bulk.assert_called_once()
		lookups.get_all.assert_called_once()

	def test_missing_product_is_reported_in_frappes_message_shape(self):
		rows = [_row("SKU-1"), _row("GONE", idx=2), _row("NP-404", "New Product", idx=3)]
		invalid, _lookups = self._check(rows, ascend_found=["SKU-1"])
		self.assertEqual(invalid, [
			("product", "GONE", "Row #2: Product: GONE"),
			("product", "NP-404", "Row #3: Product: NP-404"),
		])

	def test_alternate_identifier_resolves_and_is_stored_by_store_sku(self):
		"""Frappe's own check stored the canonical name; a row typed by UPC keeps that behavior."""
		row = _row("0123456789")
		invalid, lookups = self._check([row], alternate_matches={"0123456789": "SKU-1"})
		self.assertEqual(invalid, [])
		self.assertEqual(row.product, "SKU-1")
		lookups.single.assert_called_once()

	def test_case_differences_resolve_to_the_canonical_name(self):
		row = _row("sku-1")
		self._check([row], ascend_found=["SKU-1"])
		self.assertEqual(row.product, "SKU-1")

	def test_blank_product_type_is_treated_as_ascend_product(self):
		row = _row("SKU-1", product_type=None)
		invalid, lookups = self._check([row], ascend_found=["SKU-1"])
		self.assertEqual(invalid, [])
		lookups.bulk.assert_called_once()

	def test_row_skips_frappes_per_row_check(self):
		self.assertEqual(LocationInventory.get_invalid_links(SimpleNamespace()), ([], []))
