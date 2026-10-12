# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Field-name parity between the shipped label templates and the two doctypes they print.

The Ascend Tag and Swap Tag templates read the same attribute names whether they are handed an
Ascend Product (a virtual document) or a New Product that has not been imported yet. These tests
render each shipped template against a stand-in for both shapes, so renaming a field on either
doctype — or a template starting to read one only one of them has — fails here rather than on
the warehouse floor."""

import frappe
from frappe.tests import UnitTestCase

FIXTURE_PATH = frappe.get_app_path("bullwheel", "fixtures", "zebra_printer_label.json")

PRODUCT_FIELDS = dict(
	description="Acme Carbon Ski 170", upc="0123456789012", price=599.99, swap_price=299.95,
	online_price=349.95, brand="Acme", style_name="Carbon", size="170",
)

ASCEND_PRODUCT_SHAPE = frappe._dict(store_sku="ACM12345678I", **PRODUCT_FIELDS)
PENDING_NEW_PRODUCT_SHAPE = frappe._dict(vpn="AC-ACME-CARBON-170-1", store_sku=None, **PRODUCT_FIELDS)
NO_UPC_NEW_PRODUCT_SHAPE = frappe._dict(
	vpn="AC-ACME-CARBON-170-1", store_sku=None, **{**PRODUCT_FIELDS, "upc": None}
)

PRINTER = frappe._dict(dpi=203)
LABEL = frappe._dict(width=2.0, height=1.0)


def _fixture_label(name):
	return next(label for label in frappe.get_file_json(FIXTURE_PATH) if label["name"] == name)


def _render(label_name, document):
	label = _fixture_label(label_name)
	return frappe.render_template(
		label["zpl"], {"doc": document, "printer": PRINTER, "label": frappe._dict(width=label["width"], height=label["height"]), "quantity": 1}
	)


class UnitTestLabelTemplatesPrintNewProducts(UnitTestCase):

	def test_product_labels_target_both_doctypes(self):
		for name in ("Ascend Tag - Default", "Swap Tag - Default"):
			with self.subTest(label=name):
				targets = {row["target_doctype"] for row in _fixture_label(name)["target_doctypes"]}
				self.assertEqual(targets, {"Ascend Product", "New Product"})

	def test_templates_render_for_ascend_product_and_pending_new_product(self):
		for name in ("Ascend Tag - Default", "Swap Tag - Default"):
			for shape in (ASCEND_PRODUCT_SHAPE, PENDING_NEW_PRODUCT_SHAPE):
				with self.subTest(label=name, shape=shape.get("store_sku") or "new product"):
					zpl = _render(name, shape)
					self.assertIn("^XA", zpl)
					self.assertIn(PRODUCT_FIELDS["upc"], zpl)

	def test_pending_new_product_without_upc_falls_back_to_its_vpn_for_the_barcode(self):
		for name in ("Ascend Tag - Default", "Swap Tag - Default"):
			with self.subTest(label=name):
				self.assertIn(NO_UPC_NEW_PRODUCT_SHAPE.vpn, _render(name, NO_UPC_NEW_PRODUCT_SHAPE))

	def test_swap_tag_still_refuses_a_product_without_a_swap_price(self):
		unpriced = frappe._dict(PENDING_NEW_PRODUCT_SHAPE, swap_price=0)
		with self.assertRaises(frappe.ValidationError):
			_render("Swap Tag - Default", unpriced)
