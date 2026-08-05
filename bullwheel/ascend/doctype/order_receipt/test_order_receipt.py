# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

from types import SimpleNamespace

from frappe.tests import IntegrationTestCase, UnitTestCase

from bullwheel.ascend.doctype.order_receipt.order_receipt import (
	_order_item_to_po_row,
	_resolve_ascend_vpn,
	_single_line,
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


def fake_order_item(**values):
	"""A stand-in for an Order Receipt Item row carrying just the fields the PO projection
	reads, so the projection can be tested without a database or an Ascend connection.
	`precision` mirrors the Document method _export_cost calls for the cost field."""

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
