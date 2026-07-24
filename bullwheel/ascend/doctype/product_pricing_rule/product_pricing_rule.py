# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProductPricingRule(Document):
	def validate(self):
		if self.swap_percentage >= 1.00 or self.online_percentage >= 1.00:
			frappe.throw("Price percentage cannot be 100% (1.00) or greater.")
