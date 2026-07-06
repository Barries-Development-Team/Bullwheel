# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProductPrice(Document):
	def validate(self):
		duplicate_name = frappe.db.exists(
			"Product Price",
			{
				"pricing_type": self.pricing_type,
				"product": self.product,
				"name": ["!=", self.name],
			},
		)
		if duplicate_name:
			frappe.throw(
				f"A Product Price record already exists for product '{self.product}' with pricing type '{self.pricing_type}' ({duplicate_name})"
			)
