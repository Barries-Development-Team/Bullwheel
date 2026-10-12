# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct


class SwapTagBatchItem(Document):
	
	def _ascend_fields(self):
		"""Fetch and memoize this row's product details: an Ascend Product through the short-TTL
		cache, or a New Product (not imported into Ascend yet) from Bullwheel's own database,
		which has no average cost. Returns None when no product is set or it does not resolve."""
		if not hasattr(self, "_ascend_field_cache"):
			if not self.product:
				self._ascend_field_cache = None
			elif self.product_type == "New Product":
				self._ascend_field_cache = frappe.db.get_value(
					"New Product", self.product, ["description", "estimated_cost", "price"], as_dict=True
				)
			else:
				self._ascend_field_cache = AscendProduct.get_bulk_short_cached_values(
					[self.product], ["description", "estimated_cost", "average_cost", "price"]
				).get(self.product)
		return self._ascend_field_cache
	
	@property
	def description(self):
		fields = self._ascend_fields()
		return fields.get("description") if fields else None

	@property
	def estimated_cost(self):
		fields = self._ascend_fields()
		return fields.get("estimated_cost") if fields else None

	@property
	def average_cost(self):
		fields = self._ascend_fields()
		return fields.get("average_cost") if fields else None

	@property
	def msrp(self):
		fields = self._ascend_fields()
		return fields.get("price") if fields else None
