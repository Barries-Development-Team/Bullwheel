# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from bullwheel.ascend.doctype.vendor_product.vendor_product import PART_NUMBER_LIMIT, generate_vpn


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
