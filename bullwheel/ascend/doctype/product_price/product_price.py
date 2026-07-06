# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from sys import prefix

import frappe
from frappe.model.document import Document


class ProductPrice(Document):

	def autoname(self):
		"""Set the document name to a unique combination of pricing type and product."""
		match self.pricing_type:
			case "Ski Swap Price":
				type = "SWAP"
			case "Online Listing Price":
				type = "ONLINE"
			case _:
				raise ValueError(f"Unknown pricing type: {self.pricing_type}. Ensure that the pricing type is one of the expected values: 'Ski Swap Price' or 'Online Listing Price'.")

		self.name = f"PRICE-{type}-{self.product}"

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
