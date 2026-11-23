# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProductPricingRule(Document):
	def validate(self):
		"""Reject a discount of 100% or more, which would price the product at or below zero."""
		if (self.swap_percentage or 0) >= 1.00 or (self.online_percentage or 0) >= 1.00:
			frappe.throw("Price percentage cannot be 100% (1.00) or greater.")
