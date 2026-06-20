# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.utils.nestedset import NestedSet

class WarehouseLocation(NestedSet):
	def validate(self):
		self.validate_no_inventory_in_group()
		self.validate_non_group_has_no_children()
		self.validate_parent_is_group

	def validate_no_inventory_in_group(self):
		if self.is_group and self.location_inventory_quantities:
			frappe.throw("Group locations cannot contain inventory. Please move items to leaf locations or uncheck 'Is Group'")

	def validate_non_group_has_no_children(self):
		if not self.is_group:
			child_count = frappe.db.count('Warehouse Location', filters={'parent_warehouse_location': self.name})
			if child_count > 0:
				frappe.throw(f"Cannot uncheck 'Is Group': This location has {child_count} child location(s)")

	def validate_parent_is_group(self):
		if self.parent_warehouse_location:
			parent = frappe.get_doc('Warehouse Location', self.parent_warehouse_location)
			if not parent.is_group:
				frappe.throw(f"Parent location '{self.parent_warehouse_location}' must be a group location")
