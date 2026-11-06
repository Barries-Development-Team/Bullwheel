# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct

ASCEND_PRODUCT = "Ascend Product"
NEW_PRODUCT = "New Product"


def _product_reference_changed(row) -> bool:
	"""True when the row is new, or its product or product type differs from the saved row.
	Frappe attaches the saved copy as `_doc_before_save` (load_doc_before_save) before links are
	validated; a row without one has never been saved."""
	saved_row = getattr(row, "_doc_before_save", None)
	if saved_row is None:
		return True
	return (row.product, row.product_type or ASCEND_PRODUCT) != (saved_row.product, saved_row.product_type or ASCEND_PRODUCT)


def find_invalid_inventory_products(rows) -> list:
	"""Validate the product links of the new or changed Location Inventory `rows` in bulk, and
	return the invalid ones in Frappe's (fieldname, value, message) shape for get_invalid_links.

	Replaces Frappe's own per-row check (see LocationInventory.get_invalid_links), which loads the
	full linked Ascend Product for every row of the parent on every save — one Ascend connection and
	query per product in the bay. Here, Ascend Products are checked with one get_bulk_values query
	and New Products with one Bullwheel query, and rows whose product reference is unchanged are not
	re-checked. Like Frappe's check, each valid row's product is set to the record's canonical name,
	so a row entered by UPC or vendor part number is stored by Store SKU."""
	changed_rows = [row for row in rows if row.product and _product_reference_changed(row)]
	ascend_rows = [row for row in changed_rows if (row.product_type or ASCEND_PRODUCT) == ASCEND_PRODUCT]
	new_product_rows = [row for row in changed_rows if row.product_type == NEW_PRODUCT]

	canonical_names = {}
	if ascend_rows:
		found = AscendProduct.get_bulk_values([row.product for row in ascend_rows], ["name"])
		canonical_names.update({(ASCEND_PRODUCT, name.casefold()): name for name in found})
	if new_product_rows:
		found = frappe.get_all(NEW_PRODUCT, filters={"name": ["in", [row.product for row in new_product_rows]]}, pluck="name")
		canonical_names.update({(NEW_PRODUCT, name.casefold()): name for name in found})

	label = _(frappe.get_meta("Location Inventory").get_label("product"), context="Location Inventory")
	invalid_links = []
	for row in changed_rows:
		product_type = row.product_type or ASCEND_PRODUCT
		canonical_name = canonical_names.get((product_type, str(row.product).casefold()))
		if canonical_name is None and product_type == ASCEND_PRODUCT:
			# get_bulk_values matches Store SKUs only; a UPC or vendor part number resolves here,
			# one query per such row (rare: scan screens and check-in already store Store SKUs).
			candidates = AscendProduct.find_by_identifier(row.product, ["name"])
			canonical_name = candidates[0].name if candidates else None
		if canonical_name is None:
			invalid_links.append(("product", row.product, f"{_('Row')} #{row.idx}: {label}: {row.product}"))
		else:
			row.product = canonical_name
	return invalid_links


class LocationInventory(Document):

	def get_invalid_links(self, is_submittable=False):
		"""Skip Frappe's per-row link check: the parent validates every row's product in one bulk
		pass instead (find_invalid_inventory_products, called from
		WarehouseLocation.get_invalid_links). 'product' is this DocType's only link field, so
		nothing else goes unchecked; a new parent DocType for this table must call it too."""
		return [], []

	def _ascend_fields(self):
		"""Fetch and memoize the linked product's description/upc so both virtual fields share a
		single query per document instance: an Ascend Product from Ascend, a New Product (not
		imported yet) from Bullwheel's own database. Returns None when no product is linked or
		the linked product no longer exists."""
		if not hasattr(self, "_ascend_field_cache"):
			if not self.product:
				self._ascend_field_cache = None
			elif self.product_type == "New Product":
				self._ascend_field_cache = frappe.db.get_value(
					"New Product", self.product, ["description", "upc"], as_dict=True
				)
			else:
				self._ascend_field_cache = AscendProduct.get_values(self.product, ["description", "upc"])
		return self._ascend_field_cache

	@property
	def description(self):
		fields = self._ascend_fields()
		return fields.get("description") if fields else None

	@property
	def upc(self):
		fields = self._ascend_fields()
		return fields.get("upc") if fields else None
