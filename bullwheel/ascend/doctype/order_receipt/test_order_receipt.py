# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from bullwheel.ascend.doctype.order_receipt.order_receipt import (
	STAGED_NEW_PRODUCT_STATUSES,
	_find_staged_new_product,
	_order_item_to_po_row,
	_resolve_ascend_vpn,
	_single_line,
	_unexportable_reason,
	scan_item,
	stage_existing_product,
)


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestOrderReceipt(IntegrationTestCase):
	"""
	Integration tests for OrderReceipt.
	Use this class for testing interactions between multiple components.
	"""

	pass


@contextmanager
def fake_database(get_value):
	"""Stand in for frappe.db with just a get_value, so code that reads Bullwheel's own database
	can run in a unit test with no site connected."""
	with patch.object(frappe.local, 'db', SimpleNamespace(get_value=get_value), create=True):
		yield


def fake_order_item(**values):
	"""A stand-in for an Order Receipt Item row carrying just the fields the PO projection
	reads, so the projection can be tested without a database or an Ascend connection.
	`precision` mirrors the Document method _export_cost calls for the cost field."""

	values.setdefault('item_type', 'Vendor Product')
	values.setdefault('vpn', 'PART-1 (Helm of Sun Valley)')
	values.setdefault('description', 'Snowboard Binding')
	values.setdefault('quantity', 1)
	values.setdefault('cost', 1.0)
	values.setdefault('comments', None)
	return SimpleNamespace(precision=lambda fieldname: 2, **values)


# ─── PO row projection ────────────────────────────────────────────────────────


class UnitTestOrderItemToPoRow(UnitTestCase):

	def test_cost_is_rounded_to_the_fields_precision(self):
		"""A cost carrying full binary float precision (buyout allocations produce 16 decimal
		places) reaches the sheet rounded, so Ascend is not left to round it into its 4-decimal
		money column and inherit the artifact in every extended total."""
		row = _order_item_to_po_row(fake_order_item(cost=12.457991390177037))

		self.assertEqual(row["Cost"], 12.46)

	def test_a_cost_already_within_precision_is_unchanged(self):
		row = _order_item_to_po_row(fake_order_item(cost=8.49))

		self.assertEqual(row["Cost"], 8.49)

	def test_missing_cost_becomes_zero_rather_than_none(self):
		"""flt(None) is 0.0 — an empty Cost cell would otherwise import as a blank cost."""
		row = _order_item_to_po_row(fake_order_item(cost=None))

		self.assertEqual(row["Cost"], 0.0)

	def test_multi_line_comment_is_collapsed(self):
		"""A newline inside a Comments cell is a literal line break in the imported value.
		The whole note survives, joined onto one line."""
		row = _order_item_to_po_row(
			fake_order_item(comments="Needs the cost and MSRP added.\r\nDone 7-27-26 -Carter")
		)

		self.assertEqual(row["Comments"], "Needs the cost and MSRP added. Done 7-27-26 -Carter")

	def test_multi_line_description_is_collapsed(self):
		row = _order_item_to_po_row(fake_order_item(description="Burton Lexa\nX EST"))

		self.assertEqual(row["Description"], "Burton Lexa X EST")

	def test_empty_comment_stays_empty(self):
		"""An unset Comments field must not become the string "None"."""
		row = _order_item_to_po_row(fake_order_item(comments=None))

		self.assertIsNone(row["Comments"])

	def test_quantity_and_identifier_pass_through(self):
		row = _order_item_to_po_row(fake_order_item(vpn='BG-K2-BEDFORD-M (Helm of Sun Valley)', quantity=6))

		self.assertEqual(row["Identifier"], 'BG-K2-BEDFORD-M')
		self.assertEqual(row["Qty"], 6)


class UnitTestSingleLine(UnitTestCase):

	def test_collapses_every_flavour_of_whitespace(self):
		self.assertEqual(_single_line("a\r\nb\tc   d\n"), "a b c d")

	def test_none_and_empty_pass_through_untouched(self):
		self.assertIsNone(_single_line(None))
		self.assertEqual(_single_line(""), "")


class UnitTestResolveAscendVpn(UnitTestCase):

	def test_trailing_vendor_suffix_is_stripped(self):
		self.assertEqual(
			_resolve_ascend_vpn(fake_order_item(vpn='BG-BURTON-SCRIBE-BLACK-S (Helm of Sun Valley)')),
			'BG-BURTON-SCRIBE-BLACK-S',
		)

	def test_parentheses_inside_the_part_number_are_left_alone(self):
		self.assertEqual(
			_resolve_ascend_vpn(fake_order_item(vpn='BG-LEXA-(8+)-L (Helm of Sun Valley)')),
			'BG-LEXA-(8+)-L',
		)




class UnitTestResolveAscendVpnForNewProducts(UnitTestCase):

	def test_new_product_uses_its_own_vpn_not_the_docname(self):
		"""A New Product line's vpn holds the New Product's docname; Ascend must be given the
		part number, which is the New Product's VPN."""
		get_value = MagicMock(return_value='AB-ACME-SKI-1')
		with fake_database(get_value):
			result = _resolve_ascend_vpn(fake_order_item(item_type='New Product', vpn='NP-00001'))

		self.assertEqual(result, 'AB-ACME-SKI-1')
		get_value.assert_called_once_with('New Product', 'NP-00001', 'vpn')


class UnitTestUnexportableReason(UnitTestCase):

	def _reason(self, new_product_record):
		with fake_database(new_product_record):
			return _unexportable_reason(fake_order_item(item_type='New Product', vpn='NP-00001'))

	def test_vendor_product_lines_are_always_exportable(self):
		self.assertIsNone(_unexportable_reason(fake_order_item()))

	def test_pending_new_product_is_exportable(self):
		record = frappe._dict(status='Pending', entry_type='New Product', base_new_product=None, ascend_product=None)
		self.assertIsNone(self._reason(lambda *args, **kwargs: record))

	def test_cancelled_new_product_is_held_back(self):
		record = frappe._dict(status='Cancelled', entry_type='New Product', base_new_product=None, ascend_product=None)
		self.assertIn('cancelled', self._reason(lambda *args, **kwargs: record))

	def test_existing_product_waits_for_its_unimported_base(self):
		"""Importing the part number before its base product would make Ascend create a duplicate."""
		entry = frappe._dict(status='Pending', entry_type='Existing Product', base_new_product='NP-00009', ascend_product=None)
		base = frappe._dict(status='Exported', ascend_product=None)
		reason = self._reason(lambda doctype, name, *args, **kwargs: entry if name == 'NP-00001' else base)
		self.assertIn('NP-00009', reason)

	def test_existing_product_whose_base_is_matched_is_exportable(self):
		entry = frappe._dict(status='Pending', entry_type='Existing Product', base_new_product='NP-00009', ascend_product=None)
		base = frappe._dict(status='Imported', ascend_product='ABC12345678Z')
		self.assertIsNone(self._reason(lambda doctype, name, *args, **kwargs: entry if name == 'NP-00001' else base))


class UnitTestScanItem(UnitTestCase):
	"""scan_item checks staged New Products before Ascend, so scanning the second unit of a pending
	product adds to it instead of starting a duplicate."""

	def _scan(self, staged_for_vendor=None, ascend_rows=(), staged_for_any_vendor=None):
		fake_ascend = MagicMock()
		fake_ascend.__enter__.return_value = fake_ascend
		fake_ascend.sql.side_effect = list(ascend_rows)

		def find(identifier, vendor=None):
			return staged_for_vendor if vendor else staged_for_any_vendor

		module = 'bullwheel.ascend.doctype.order_receipt.order_receipt'
		with (
			patch(f'{module}._resolve_vendor_id', return_value='VENDOR-ID'),
			patch(f'{module}._find_staged_new_product', side_effect=find),
			patch(f'{module}.MSSQLDatabase', return_value=fake_ascend),
			patch(f'{module}.get_default_ascend_database', return_value=None),
		):
			return scan_item('0123456789', 'Acme'), fake_ascend

	def test_staged_product_for_this_vendor_wins_without_touching_ascend(self):
		staged = frappe._dict(name='NP-00001', cost=10)
		(status, record), ascend = self._scan(staged_for_vendor=staged)
		self.assertEqual((status, record.name), ('new product found', 'NP-00001'))
		ascend.sql.assert_not_called()

	def test_vendor_product_in_ascend_is_found_next(self):
		(status, record), _ = self._scan(ascend_rows=[[{'vpn': 'PART-1', 'cost': 5, 'description': 'x', 'upc': 'u'}]])
		self.assertEqual((status, record['vpn']), ('vpn found', 'PART-1 (Acme)'))

	def test_ascend_product_is_found_before_another_vendors_pending_product(self):
		(status, _), _ = self._scan(
			ascend_rows=[[], [{'product_id': 1, 'store_sku': 'ABC'}]],
			staged_for_any_vendor=frappe._dict(name='NP-00002'),
		)
		self.assertEqual(status, 'product found')

	def test_another_vendors_pending_product_is_offered_when_ascend_has_nothing(self):
		(status, record), _ = self._scan(ascend_rows=[[], []], staged_for_any_vendor=frappe._dict(name='NP-00002'))
		self.assertEqual((status, record.name), ('pending product found', 'NP-00002'))

	def test_nothing_anywhere_is_not_found(self):
		(status, record), _ = self._scan(ascend_rows=[[], []])
		self.assertEqual((status, record), ('not found', None))


class UnitTestFindStagedNewProduct(UnitTestCase):

	def test_searches_only_products_still_staged_and_scopes_to_the_vendor(self):
		with patch('bullwheel.ascend.doctype.order_receipt.order_receipt.frappe.get_all', return_value=[]) as get_all:
			_find_staged_new_product('0123', 'Acme')

		filters = get_all.call_args.kwargs['filters']
		self.assertEqual(filters['status'], ['in', STAGED_NEW_PRODUCT_STATUSES])
		self.assertNotIn('Imported', STAGED_NEW_PRODUCT_STATUSES)
		self.assertEqual(filters['vendor'], 'Acme')

	def test_without_a_vendor_every_vendors_products_are_searched(self):
		with patch('bullwheel.ascend.doctype.order_receipt.order_receipt.frappe.get_all', return_value=[]) as get_all:
			_find_staged_new_product('0123')

		self.assertNotIn('vendor', get_all.call_args.kwargs['filters'])


class UnitTestStageExistingProduct(UnitTestCase):

	def test_needs_exactly_one_source_product(self):
		for kwargs in ({}, {'ascend_product': 'A', 'base_new_product': 'NP-1'}):
			with self.subTest(kwargs=kwargs):
				with self.assertRaises(frappe.ValidationError):
					stage_existing_product('PO-1', 'VPN-1', 5, **kwargs)
