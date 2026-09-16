# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from bullwheel.ascend.doctype.product_price.product_price import get_swap_prices, set_swap_prices


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestProductPrice(IntegrationTestCase):
	"""
	Integration tests for ProductPrice.
	Use this class for testing interactions between multiple components.
	"""

	pass


# Ascend Product is a virtual doctype backed by a live SQL Server connection, so these
# tests mock frappe's query/write seams (the same approach test_resolution.py and
# test_bullwheel_core.py take) rather than inserting real Product Price documents.
_MODULE = "bullwheel.ascend.doctype.product_price.product_price"


class UnitTestGetSwapPrices(UnitTestCase):
	"""get_swap_prices bulk-fetches Ski Swap Price values in one query."""

	def test_returns_price_for_each_requested_product(self):
		"""Products with a Product Price record resolve to their price; missing ones resolve to None."""
		rows = [frappe._dict({"product": "PROD-1", "price": 12.5})]
		with patch(f"{_MODULE}.frappe.get_all", return_value=rows) as mock_get_all:
			result = get_swap_prices(["PROD-1", "PROD-2"])

		self.assertEqual(result, {"PROD-1": 12.5, "PROD-2": None})
		mock_get_all.assert_called_once_with(
			"Product Price",
			filters={"pricing_type": "Ski Swap Price", "product": ["in", ["PROD-1", "PROD-2"]]},
			fields=["product", "price"],
		)

	def test_empty_product_list_returns_empty_dict_without_querying(self):
		"""No products means no query is needed."""
		with patch(f"{_MODULE}.frappe.get_all") as mock_get_all:
			result = get_swap_prices([])

		self.assertEqual(result, {})
		mock_get_all.assert_not_called()

	def test_accepts_a_json_string_of_products(self):
		"""frappe.call may deliver a list argument as a JSON string."""
		with patch(f"{_MODULE}.frappe.get_all", return_value=[]):
			result = get_swap_prices('["PROD-1"]')

		self.assertEqual(result, {"PROD-1": None})

	def test_duplicate_products_are_deduplicated(self):
		"""A repeated product name should not appear twice in the filter or the result."""
		with patch(f"{_MODULE}.frappe.get_all", return_value=[]) as mock_get_all:
			get_swap_prices(["PROD-1", "PROD-1"])

		mock_get_all.assert_called_once_with(
			"Product Price",
			filters={"pricing_type": "Ski Swap Price", "product": ["in", ["PROD-1"]]},
			fields=["product", "price"],
		)


class UnitTestSetSwapPrices(UnitTestCase):
	"""set_swap_prices upserts Ski Swap Price records for multiple products in one call."""

	def test_updates_price_on_an_existing_record(self):
		"""An existing Product Price record only has its price field written, never product/pricing_type."""
		with (
			patch(f"{_MODULE}.frappe.db.exists", return_value=True) as mock_exists,
			patch(f"{_MODULE}.frappe.db.set_value") as mock_set_value,
			patch(f"{_MODULE}.frappe.get_doc") as mock_get_doc,
		):
			set_swap_prices({"PROD-1": 19.99})

		mock_exists.assert_called_once_with("Product Price", "PRICE-SWAP-PROD-1")
		mock_set_value.assert_called_once_with("Product Price", "PRICE-SWAP-PROD-1", "price", 19.99)
		mock_get_doc.assert_not_called()

	def test_inserts_a_new_record_when_none_exists(self):
		"""A product with no Product Price record yet gets one inserted with pricing_type set."""
		new_doc = MagicMock()
		with (
			patch(f"{_MODULE}.frappe.db.exists", return_value=False),
			patch(f"{_MODULE}.frappe.db.set_value") as mock_set_value,
			patch(f"{_MODULE}.frappe.get_doc", return_value=new_doc) as mock_get_doc,
		):
			set_swap_prices({"PROD-2": 5})

		mock_set_value.assert_not_called()
		mock_get_doc.assert_called_once_with(
			{
				"doctype": "Product Price",
				"product": "PROD-2",
				"pricing_type": "Ski Swap Price",
				"price": 5.0,
			}
		)
		new_doc.insert.assert_called_once()

	def test_empty_prices_does_nothing(self):
		"""No prices means no database calls at all."""
		with (
			patch(f"{_MODULE}.frappe.db.exists") as mock_exists,
			patch(f"{_MODULE}.frappe.get_doc") as mock_get_doc,
		):
			set_swap_prices({})

		mock_exists.assert_not_called()
		mock_get_doc.assert_not_called()

	def test_accepts_a_json_string_of_prices(self):
		"""frappe.call may deliver a dict argument as a JSON string."""
		with (
			patch(f"{_MODULE}.frappe.db.exists", return_value=True),
			patch(f"{_MODULE}.frappe.db.set_value") as mock_set_value,
		):
			set_swap_prices('{"PROD-1": 10}')

		mock_set_value.assert_called_once_with("Product Price", "PRICE-SWAP-PROD-1", "price", 10.0)
