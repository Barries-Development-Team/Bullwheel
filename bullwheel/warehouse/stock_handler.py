# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe

@frappe.whitelist()
def get_locations_for_product(product):
	"""Return all Warehouse Locations that contain the given product, with quantity.

	Queries the Location Inventory child table for rows matching the product name
	and returns each parent Warehouse Location paired with its on-hand quantity.
	"""
	rows = frappe.db.get_all(
		"Location Inventory",
		filters={"product": product, "parenttype": "Warehouse Location"},
		fields=["parent", "quantity"],
		order_by="parent asc",
	)
	return rows

def checkout_item(item_id: str, bay: str):
    frappe.get_doc('Warehouse Location',)