# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from bullwheel.ascend.doctype.vendor_product.vendor_product import (
	PART_NUMBER_LIMIT,
	create_vendor_product,
	generate_vpn,
)
from bullwheel.bullwheel_core.exceptions import AscendAttributionUserNotConfigured


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestVendorProduct(IntegrationTestCase):
	"""
	Integration tests for VendorProduct.
	Use this class for testing interactions between multiple components.
	"""

	pass


# ─── generate_vpn — PART_NUMBER_LIMIT enforcement ──────────────────────────────


class UnitTestGenerateVpnCharacterLimit(UnitTestCase):

	def test_model_is_truncated_to_fit_the_limit(self):
		"""A base VPN over PART_NUMBER_LIMIT gets "model" trimmed by exactly the overage."""
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.sql.return_value = []  # no existing VendorProducts row for any candidate

		with (
			patch('bullwheel.ascend.doctype.vendor_product.vendor_product.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.doctype.vendor_product.vendor_product.get_default_ascend_database', return_value=None),
		):
			result = generate_vpn(vendor_id=1, vpn_prefix='AB', brand='CD', model='M' * 50)

		expected_base = f"AB-CD-{'M' * 39}"
		self.assertEqual(len(expected_base), PART_NUMBER_LIMIT)
		self.assertEqual(result, f"{expected_base}-1")

	def test_throws_when_still_over_limit_after_truncating_model(self):
		"""If the non-model components alone already exceed the limit, truncating "model" to
		nothing still can't fit — this must raise instead of silently inserting an oversized
		PartNumber into Ascend."""
		with self.assertRaises(frappe.ValidationError):
			generate_vpn(vendor_id=1, vpn_prefix='A' * 50, brand='CD', model='M')


# ─── create_vendor_product — Ascend edit attribution ───────────────────────────


class UnitTestCreateVendorProductAttribution(UnitTestCase):
	"""A VendorProducts row Bullwheel inserts must carry a real Ascend CreatorID/ModifierID.
	Ascend refuses to save an order referencing a vendor product with no creator, so an
	unattributed insert here surfaces much later as an order that will not save."""

	def _patched_create(self, fake_database, resolved_user_id='ASCEND-USER-ID'):
		"""Run create_vendor_product against a mocked Ascend connection and a stubbed user
		resolution, returning the mock so the caller can assert on the executed INSERT."""
		return patch.multiple(
			'bullwheel.ascend.doctype.vendor_product.vendor_product',
			MSSQLDatabase=MagicMock(return_value=fake_database),
			get_default_ascend_database=MagicMock(return_value=None),
			resolve_attributed_ascend_user_id=MagicMock(return_value=resolved_user_id),
		)

	def _fake_database(self):
		"""A mocked MSSQLDatabase context manager reporting no existing part-number match and
		exactly one inserted row, so create_vendor_product runs its INSERT path to completion."""
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.sql.return_value = []  # no existing VendorProducts row for this part number
		fake_database.cursor.rowcount = 1
		return fake_database

	def test_insert_supplies_creator_and_modifier_ids(self):
		"""The INSERT names CreatorID and ModifierID, and binds the resolved Ascend user id to
		both."""
		fake_database = self._fake_database()

		with self._patched_create(fake_database):
			inserted = create_vendor_product(
				vendor_id=1, product_id=2, part_number='PART-1', cost=9.99, description='Item',
			)

		self.assertTrue(inserted)
		query, values = fake_database.sql.call_args_list[-1][0][:2]
		self.assertIn('CreatorID', query)
		self.assertIn('ModifierID', query)
		self.assertEqual(values.count('ASCEND-USER-ID'), 2)
		# One placeholder per bound value, or pymssql binds them to the wrong columns.
		self.assertEqual(query.count('%s'), len(values))

	def test_unresolvable_user_aborts_before_inserting(self):
		"""With neither a linked Ascend User nor a usable default_user, the insert is refused
		outright rather than writing a row with a null CreatorID."""
		fake_database = self._fake_database()

		with patch.multiple(
			'bullwheel.ascend.doctype.vendor_product.vendor_product',
			MSSQLDatabase=MagicMock(return_value=fake_database),
			get_default_ascend_database=MagicMock(return_value=None),
			resolve_attributed_ascend_user_id=MagicMock(side_effect=AscendAttributionUserNotConfigured),
		):
			with self.assertRaises(frappe.ValidationError):
				create_vendor_product(
					vendor_id=1, product_id=2, part_number='PART-1', cost=9.99,
				)

		fake_database.sql.assert_not_called()
