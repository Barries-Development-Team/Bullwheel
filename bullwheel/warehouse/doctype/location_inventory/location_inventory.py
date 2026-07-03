# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct


class LocationInventory(Document):

	def _ascend_fields(self):
		"""Fetch and memoize the linked Ascend Product's mirrored fields so both virtual
		fields share a single SQL query per document instance. Returns None when no product
		is linked or the linked product no longer exists in Ascend."""
		if not hasattr(self, "_ascend_field_cache"):
			self._ascend_field_cache = (
				AscendProduct.get_values(self.product, ["description", "upc"])
				if self.product else None
			)
		return self._ascend_field_cache

	@property
	def description(self):
		fields = self._ascend_fields()
		return fields.get("description") if fields else None

	@property
	def upc(self):
		fields = self._ascend_fields()
		return fields.get("upc") if fields else None
