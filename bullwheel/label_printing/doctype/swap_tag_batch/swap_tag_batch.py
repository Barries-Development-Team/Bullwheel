# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from bullwheel.ascend.doctype.product_price.product_price import get_swap_prices


class SwapTagBatch(Document):
	def before_save(self):
		"""Refresh every row's swap price from its product's live price: the Product Price record
		for an Ascend Product, or the New Product's own price while it awaits import."""
		live_prices = get_swap_prices([
			{"doctype": row.product_type, "name": row.product} for row in self.swap_tag_items if row.product
		])
		for row in self.swap_tag_items:
			row.swap_price = live_prices.get(row.product)
