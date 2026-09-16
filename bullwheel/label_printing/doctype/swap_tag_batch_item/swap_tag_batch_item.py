# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct


class SwapTagBatchItem(Document):
	
	def _ascend_fields(self):
		if not hasattr(self, "_ascend_field_cache"):
			self._ascend_field_cache = (
				AscendProduct.get_bulk_short_cached_values([self.product], ["description", "estimated_cost", "average_cost", "price"]).get(self.product)
				if self.product else None
			)
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
