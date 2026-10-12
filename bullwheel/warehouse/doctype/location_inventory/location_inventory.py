# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct


class LocationInventory(Document):

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
