# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.utils.nestedset import NestedSet

from bullwheel.warehouse.doctype.location_inventory.location_inventory import find_invalid_inventory_products

class WarehouseLocation(NestedSet):

	def get_invalid_links(self, is_submittable=False):
		"""Frappe's link check for this location, plus a bulk check of its inventory rows' products
		(Location Inventory skips its own per-row check, which loaded every row's Ascend Product on
		every save). Invalid products are reported through Frappe's usual "Could not find" error."""
		invalid_links, cancelled_links = super().get_invalid_links(is_submittable)
		invalid_links.extend(find_invalid_inventory_products(self.location_inventory_quantities))
		return invalid_links, cancelled_links

	@property
	def total_inventory(self):
		total = 0
		for item in self.location_inventory_quantities:
			total += item.quantity or 0
		return total

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
