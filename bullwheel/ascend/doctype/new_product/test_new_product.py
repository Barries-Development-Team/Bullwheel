# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

# import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestNewProduct(IntegrationTestCase):
	"""
	Integration tests for NewProduct.
	Use this class for testing interactions between multiple components.
	"""

	pass


# ─── to_import_row ─────────────────────────────────────────────────────────────

import frappe
from frappe.tests import UnitTestCase

from bullwheel.ascend.doctype.new_product.new_product import (
	STATUS_ACTIONS,
	TEMPLATE_COLUMN_TO_FIELD,
	to_import_row,
)


def _new_product_record(**overrides):
	record = frappe._dict(
		entry_type="New Product", vpn="AB-ACME-SKI-1", category="Skis", brand="Acme",
		description="Acme Ski", estimated_cost=100.0, price=250.0, upc="0123456789",
		color="Red", size="170", style_number="S1", style_name="Ski", year="2027",
		gender="Men", season="W27", manufacturers_part_number="MPN-1",
		case=0, case_quantity=None, case_upc=None, case_msrp=None,
	)
	record.update(overrides)
	return record


class UnitTestToImportRow(UnitTestCase):

	def test_every_mapped_field_exists_on_new_product(self):
		"""A column mapped to a fieldname the DocType lacks exports blank silently (the old
		'cast_msrp' typo did exactly that), so every mapping must name a real field."""
		fieldnames = {field["fieldname"] for field in frappe.get_file_json(
			frappe.get_app_path("bullwheel", "ascend", "doctype", "new_product", "new_product.json")
		)["fields"]}
		self.assertEqual(set(TEMPLATE_COLUMN_TO_FIELD.values()) - fieldnames, set())

	def test_cost_msrp_and_mpn_come_from_the_real_fields(self):
		row = to_import_row(_new_product_record())
		self.assertEqual(row["Cost"], 100.0)
		self.assertEqual(row["MSRP"], 250.0)
		self.assertEqual(row["MPN"], "MPN-1")
		self.assertEqual(row["VPN"], "AB-ACME-SKI-1")

	def test_case_columns_only_present_for_cased_products(self):
		self.assertNotIn("CaseQty", to_import_row(_new_product_record()))
		cased = to_import_row(_new_product_record(case=1, case_quantity=6, case_upc="999", case_msrp=1500.0))
		self.assertEqual((cased["CaseQty"], cased["CaseUPC"], cased["CaseMSRP"]), (6, "999", 1500.0))

	def test_id_and_non_inventory_columns_stay_blank(self):
		row = to_import_row(_new_product_record())
		for column in ("ID", "IsNonInventory", "eCommerce"):
			self.assertNotIn(column, row)

	def test_existing_product_row_only_identifies_the_product_and_vendor_part(self):
		"""Sending category/brand/etc. for an existing product could overwrite its attributes."""
		row = to_import_row(_new_product_record(entry_type="Existing Product"))
		self.assertEqual(set(row), {"VPN", "Description", "Cost", "UPC"})
		self.assertEqual(row["UPC"], "0123456789")


class UnitTestStatusActions(UnitTestCase):

	def test_imported_is_never_a_starting_status(self):
		"""Imported records are final: no action may leave that status."""
		for action, (allowed_from, _) in STATUS_ACTIONS.items():
			with self.subTest(action=action):
				self.assertNotIn("Imported", allowed_from)

	def test_cancel_is_not_offered_once_exported(self):
		self.assertNotIn("Exported", STATUS_ACTIONS["cancel"][0])


# ─── Pricing (Product Pricing Rule charm price, prices above cost) ─────────────

from types import SimpleNamespace
from unittest.mock import patch

from bullwheel.ascend.doctype.new_product.new_product import (
	NewProduct,
	apply_charm_price,
	compute_swap_and_online_price,
	prices_below_minimum_margin,
)


class UnitTestComputeSwapAndOnlinePrice(UnitTestCase):

	def _compute(self, msrp, charm_price=None, swap_percentage=0.5, online_percentage=0.4):
		rule = frappe._dict(swap_percentage=swap_percentage, online_percentage=online_percentage, charm_price=charm_price)
		with patch.object(frappe, "get_cached_doc", return_value=rule):
			return compute_swap_and_online_price(msrp, "Any Rule")

	def test_missing_msrp_returns_zero_prices_without_error(self):
		"""Issue #73: picking a rule before the MSRP is filled in used to raise a server error."""
		for msrp in (None, 0, ""):
			self.assertEqual(compute_swap_and_online_price(msrp, "Any Rule"), {"swap_price": 0.0, "online_price": 0.0})
		self.assertEqual(compute_swap_and_online_price(), {"swap_price": 0.0, "online_price": 0.0})

	def test_missing_rule_returns_zero_prices(self):
		self.assertEqual(compute_swap_and_online_price(250.0, None), {"swap_price": 0.0, "online_price": 0.0})

	def test_unset_charm_price_keeps_the_original_95_ending(self):
		self.assertEqual(self._compute(250.0), {"swap_price": 124.95, "online_price": 149.95})

	def test_each_charm_price_ending(self):
		self.assertEqual(self._compute(250.0, ".95"), {"swap_price": 124.95, "online_price": 149.95})
		self.assertEqual(self._compute(250.0, ".99"), {"swap_price": 124.99, "online_price": 149.99})
		self.assertEqual(self._compute(250.0, ".00"), {"swap_price": 125.0, "online_price": 150.0})

	def test_msrp_sent_as_text_by_the_form_is_accepted(self):
		self.assertEqual(self._compute("250"), {"swap_price": 124.95, "online_price": 149.95})


class UnitTestApplyCharmPrice(UnitTestCase):

	def test_rounds_to_the_nearest_dollar_before_the_ending(self):
		self.assertEqual(apply_charm_price(99.6, ".95"), 99.95)
		self.assertEqual(apply_charm_price(99.4, ".99"), 98.99)
		self.assertEqual(apply_charm_price(99.4, ".00"), 99.0)

	def test_never_negative(self):
		self.assertEqual(apply_charm_price(0.3, ".95"), 0)
		self.assertEqual(apply_charm_price(0.3, ".00"), 0)

	def test_unknown_ending_raises(self):
		with self.assertRaises(frappe.ValidationError):
			apply_charm_price(100.0, ".49")


class UnitTestPricesBelowMinimumMargin(UnitTestCase):

	def test_prices_above_cost_pass_with_no_margin(self):
		self.assertEqual(prices_below_minimum_margin(100.0, {"Swap Price": 100.01, "Online Price": 150.0}), [])

	def test_price_at_or_below_cost_fails_with_no_margin(self):
		problems = prices_below_minimum_margin(100.0, {"Swap Price": 100.0, "Online Price": 80.0})
		self.assertEqual(len(problems), 2)
		self.assertIn("Swap Price $100.00", problems[0])

	def test_margin_raises_the_minimum(self):
		problems = prices_below_minimum_margin(100.0, {"Swap Price": 119.0, "Online Price": 120.0}, 0.2)
		self.assertEqual(len(problems), 1)
		self.assertIn("at least $120.00", problems[0])

	def test_empty_prices_are_not_checked(self):
		self.assertEqual(prices_below_minimum_margin(100.0, {"Swap Price": None, "Online Price": 0}, 0.2), [])


class UnitTestUpcWhitespace(UnitTestCase):

	def _record(self, upc=None, case_upc=None, is_new=True, changed=()):
		"""A stand-in for a New Product exposing just what the UPC check reads."""
		values = {"upc": upc, "case_upc": case_upc}
		return SimpleNamespace(
			get=values.get,
			is_new=lambda: is_new,
			has_value_changed=lambda fieldname: fieldname in changed,
		)

	def test_upc_with_whitespace_is_rejected(self):
		for upc in ("0123 456789", " 0123456789", "0123456789\t", "0123456789\n"):
			with self.assertRaises(frappe.ValidationError):
				NewProduct._validate_upcs_have_no_whitespace(self._record(upc=upc))

	def test_case_upc_with_whitespace_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			NewProduct._validate_upcs_have_no_whitespace(self._record(upc="0123456789", case_upc="999 1"))

	def test_clean_or_empty_upcs_pass(self):
		NewProduct._validate_upcs_have_no_whitespace(self._record(upc="0123456789", case_upc="9991"))
		NewProduct._validate_upcs_have_no_whitespace(self._record())

	def test_unchanged_legacy_value_is_not_rechecked(self):
		"""Reconciliation re-saves imported records; an old UPC must not block that save."""
		NewProduct._validate_upcs_have_no_whitespace(self._record(upc="0123 456789", is_new=False))
		with self.assertRaises(frappe.ValidationError):
			NewProduct._validate_upcs_have_no_whitespace(self._record(upc="0123 456789", is_new=False, changed=("upc",)))
