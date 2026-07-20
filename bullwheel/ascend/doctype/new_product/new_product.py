# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import random

import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct
from bullwheel.ascend.doctype.vendor.vendor import Vendor
from bullwheel.ascend.doctype.vendor_product.vendor_product import create_vendor_product

# Maps Ascend Vendor Products template column headers to New Product fieldnames.
# Columns absent from this map (ID, IsNonInventory, eCommerce, Color Code, JH QTY)
# are left blank because they have no equivalent field in the New Product DocType.
TEMPLATE_COLUMN_TO_FIELD = {
	"VPN": "vpn",
	"Category": "category",
	"Brand": "brand",
	"Description": "description",
	"Cost": "cost",
	"MSRP": "msrp",
	"UPC": "upc",
	"Color": "color",
	"Size": "size",
	"StyleNumber": "style_number",
	"StyleName": "style_name",
	"Year": "year",
	"Gender": "gender",
	"Season": "season",
	"MPN": "mpn",
	"CaseQty": "case_quantity",
	"CaseUPC": "case_upc",
	"CaseMSRP": "cast_msrp",
}

CASE_COLUMNS = {"CaseQty", "CaseUPC", "CaseMSRP"}

# New Product fieldnames that map onto an Ascend Product field of the same name.
ASCEND_PRODUCT_FIELDS = [
	"description", "price", "estimated_cost", "upc", "manufacturers_part_number",
	"brand", "color", "size", "style_name", "style_number", "season", "year", "gender",
]

STORE_SKU_RANDOM_DIGITS = 8
MAX_STORE_SKU_ATTEMPTS = 20


def _generate_store_sku(description):
	"""Build a new Ascend Store SKU: the first 3 letters of `description`, then
	STORE_SKU_RANDOM_DIGITS random digits, then its last letter, all upper-cased. Retries
	against Ascend on collision — the random digits make one vanishingly unlikely, but a fresh
	Products table lookup backs every attempt rather than trusting a single draw to be unique."""
	prefix = description[:3].upper()
	suffix = description[-1:].upper()

	for _ in range(MAX_STORE_SKU_ATTEMPTS):
		digits = "".join(str(random.randint(0, 9)) for _ in range(STORE_SKU_RANDOM_DIGITS))
		candidate = f"{prefix}{digits}{suffix}"
		if not AscendProduct._record_exists(candidate):
			return candidate

	frappe.throw(f"Could not generate a unique Store SKU after {MAX_STORE_SKU_ATTEMPTS} attempts.")


class NewProduct(Document):
	def autoname(self):
		"""Generate the Store SKU up front. It doubles as this document's own name (the
		"field:store_sku" autoname rule picks up whatever this sets) and as the Ascend
		Product's primary key created in after_insert, so it must exist before either naming
		step runs."""
		if not self.store_sku:
			self.store_sku = _generate_store_sku(self.description)

	def validate(self):
		pass

	def after_insert(self):
		"""Create the Ascend Product this New Product represents, then — when a vendor was
		seeded onto this document (see Order Receipt's open_new_product_quick_entry) — the
		Vendor Product linking it to that vendor. Runs after the local New Product record is
		committed, so a Store SKU collision or Ascend connectivity failure surfaces as an
		ordinary insert error rather than leaving Ascend and Bullwheel out of sync."""
		ascend_product = frappe.get_doc({
			"doctype": "Ascend Product",
			"store_sku": self.store_sku,
			**{field: self.get(field) for field in ASCEND_PRODUCT_FIELDS},
		})
		ascend_product.insert()

		if not self.vendor:
			return

		vendor_record = Vendor.get_values(self.vendor, ["id"])
		if not vendor_record:
			frappe.throw(f'Vendor "{self.vendor}" was not found in Ascend.')

		product_record = AscendProduct.get_values(self.store_sku, ["id"])
		create_vendor_product(
			vendor_id=vendor_record["id"],
			product_id=product_record["id"],
			part_number=self.vpn,
			cost=self.estimated_cost,
			description=self.description,
			case_quantity=self.case_quantity if self.case else None,
			case_upc=self.case_upc if self.case else None,
			case_msrp=self.case_msrp if self.case else None,
		)


def to_import_row(product):
	"""Project one New Product row onto the Ascend Vendor Products template column headers,
	returning a {template_column: value} dict. The case columns are dropped when the row
	carries no case. Duck-typed on `product` (reads attributes by fieldname), so it serves
	both Order Receipt's `new_products` rows and Bulk Product Import's `table_frll` rows."""
	row = {}
	for template_column, field_name in TEMPLATE_COLUMN_TO_FIELD.items():
		if template_column in CASE_COLUMNS and not product.case:
			continue
		row[template_column] = getattr(product, field_name, None)
	return row
