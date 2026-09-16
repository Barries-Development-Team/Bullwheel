# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SwapTagBatch(Document):
	def before_save(self):
		for row in self.swap_tag_items:
			row.swap_price = frappe.get_value('Product Price', f'PRICE-SWAP-{row.product}', 'price')