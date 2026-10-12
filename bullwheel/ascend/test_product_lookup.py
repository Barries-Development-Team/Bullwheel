# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for resolving scanned identifiers and stored product references to a product that
may be an Ascend Product or a New Product still waiting to be imported."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.ascend import product_lookup
from bullwheel.ascend.doctype.product_price import product_price
from bullwheel.test_support import patch_database

LOOKUP = 'bullwheel.ascend.product_lookup'


def _ascend_product(name='ABC12345678Z', description='Ski', upc='0123456789'):
	return frappe._dict(name=name, description=description, upc=upc)


class UnitTestEffectiveProduct(UnitTestCase):

	def test_ascend_product_reads_as_itself(self):
		self.assertEqual(product_lookup.effective_product('Ascend Product', 'ABC'), ('Ascend Product', 'ABC'))

	def test_pending_new_product_reads_as_itself(self):
		with patch_database(SimpleNamespace(get_value=lambda *args, **kwargs: None)):
			self.assertEqual(product_lookup.effective_product('New Product', 'NP-1'), ('New Product', 'NP-1'))

	def test_imported_new_product_reads_as_its_ascend_product(self):
		"""A bay row saved before the import keeps showing live Ascend data afterwards."""
		with patch_database(SimpleNamespace(get_value=lambda *args, **kwargs: 'ABC12345678Z')):
			self.assertEqual(product_lookup.effective_product('New Product', 'NP-1'), ('Ascend Product', 'ABC12345678Z'))


class UnitTestResolveScannedProduct(UnitTestCase):

	def test_blank_input_resolves_to_nothing(self):
		self.assertIsNone(product_lookup.resolve_scanned_product('   '))

	def test_ascend_product_is_preferred(self):
		with patch(f'{LOOKUP}.AscendProduct.get_values', return_value=_ascend_product()):
			result = product_lookup.resolve_scanned_product('0123456789')
		self.assertEqual(result['doctype'], 'Ascend Product')
		self.assertEqual(result['name'], 'ABC12345678Z')

	def test_pending_new_product_is_the_fallback(self):
		pending = frappe._dict(name='NP-1', description='New ski', upc='999', ascend_product=None)
		with (
			patch(f'{LOOKUP}.AscendProduct.get_values', return_value=None),
			patch(f'{LOOKUP}.frappe.get_all', return_value=[pending]),
		):
			result = product_lookup.resolve_scanned_product('999')
		self.assertEqual((result['doctype'], result['name']), ('New Product', 'NP-1'))

	def test_matched_new_product_resolves_to_its_ascend_product(self):
		matched = frappe._dict(name='NP-1', description='stale', upc='999', ascend_product='ABC12345678Z')
		with (
			patch(f'{LOOKUP}.AscendProduct.get_values', side_effect=[None, _ascend_product()]),
			patch(f'{LOOKUP}.frappe.get_all', return_value=[matched]),
		):
			result = product_lookup.resolve_scanned_product('999')
		self.assertEqual((result['doctype'], result['name']), ('Ascend Product', 'ABC12345678Z'))

	def test_unknown_identifier_resolves_to_nothing(self):
		with (
			patch(f'{LOOKUP}.AscendProduct.get_values', return_value=None),
			patch(f'{LOOKUP}.frappe.get_all', return_value=[]),
		):
			self.assertIsNone(product_lookup.resolve_scanned_product('nope'))


class UnitTestSwapPrices(UnitTestCase):
	"""get_swap_prices / set_swap_prices read and write the right place for each product type."""

	def test_prices_come_from_product_price_for_ascend_and_from_the_new_product_otherwise(self):
		def get_all(doctype, **kwargs):
			if doctype == 'Product Price':
				return [frappe._dict(product='ABC', price=199.0)]
			return [frappe._dict(name='NP-1', swap_price=0), frappe._dict(name='NP-2', swap_price=250.0)]

		with (
			patch_database(SimpleNamespace(get_value=lambda *args, **kwargs: None)),
			patch(f'{product_price.__name__}.frappe.get_all', side_effect=get_all),
		):
			prices = product_price.get_swap_prices([
				{'doctype': 'Ascend Product', 'name': 'ABC'},
				{'doctype': 'New Product', 'name': 'NP-1'},
				{'doctype': 'New Product', 'name': 'NP-2'},
			])

		self.assertEqual(prices, {'ABC': 199.0, 'NP-1': None, 'NP-2': 250.0})

	def test_bare_names_are_treated_as_ascend_products(self):
		with patch(f'{product_price.__name__}.frappe.get_all', return_value=[]):
			self.assertEqual(product_price.get_swap_prices(['ABC']), {'ABC': None})

	def test_new_product_price_is_written_without_running_its_validation(self):
		database = MagicMock(get_value=lambda *args, **kwargs: None)
		with patch_database(database):
			product_price.set_swap_prices([{'doctype': 'New Product', 'name': 'NP-1', 'price': 125}])

		database.set_value.assert_called_once_with('New Product', 'NP-1', 'swap_price', 125.0)

	def test_ascend_product_price_updates_the_existing_product_price_record(self):
		database = MagicMock(get_value=lambda *args, **kwargs: None)
		database.exists.return_value = True
		with patch_database(database):
			product_price.set_swap_prices({'ABC': 150})

		database.set_value.assert_called_once_with('Product Price', 'PRICE-SWAP-ABC', 'price', 150.0)
