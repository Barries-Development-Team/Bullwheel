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
