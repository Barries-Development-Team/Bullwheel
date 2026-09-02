# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct


class SwapTagBatchItem(Document):
	
	@property
	def description(self):
		return AscendProduct.get_cached_value(self.product, "description")
