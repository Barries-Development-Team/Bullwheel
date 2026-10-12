# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe
from frappe.utils import cint

from bullwheel.ascend.product_lookup import effective_product

@frappe.whitelist()
def get_product_locations(product: str, product_type: str = "Ascend Product") -> list:
	"""Return all Warehouse Locations that contain the given product, with quantity.

	Queries the Location Inventory child table for rows matching the product (an Ascend
	Product, or a New Product still waiting to be imported) and returns each parent
	Warehouse Location paired with its on-hand quantity. A New Product already matched to its
	Ascend Product is looked up as that Ascend Product.
	"""
	product_type, product = effective_product(product_type, product)
	rows = frappe.db.get_all(
		"Location Inventory",
		filters={"product": product, "product_type": product_type, "parenttype": "Warehouse Location"},
		fields=["parent", "product", "quantity"],
		order_by="parent asc",
	)
	return rows


def _get_inventory_row(warehouse_location, product, product_type):
	"""Return the Location Inventory row for the given product on this Warehouse Location
	document, or None if the location has no on-hand quantity of that product."""
	return next(
		(
			row for row in warehouse_location.location_inventory_quantities
			if row.product == product and (row.product_type or "Ascend Product") == product_type
		),
		None,
	)


@frappe.whitelist()
def check_in_item(product: str, location: str, quantity: int = 1, product_type: str = "Ascend Product"):
	"""Add the given quantity of a product to a Warehouse Location's on-hand inventory.

	Increments the matching Location Inventory row if the location already stores the
	product, otherwise appends a new row. Loads the Warehouse Location document so
	standard validation (e.g. group locations cannot hold inventory) still applies.
	"""
	quantity = cint(quantity)
	if quantity <= 0:
		frappe.throw("Quantity must be greater than zero.")

	product_type, product = effective_product(product_type, product)
	warehouse_location = frappe.get_doc("Warehouse Location", location)
	existing_row = _get_inventory_row(warehouse_location, product, product_type)

	if existing_row:
		existing_row.quantity = cint(existing_row.quantity) + quantity
	else:
		warehouse_location.append("location_inventory_quantities", {
			"product_type": product_type,
			"product": product,
			"quantity": quantity,
		})

	warehouse_location.save()
	return warehouse_location.name


@frappe.whitelist()
def check_out_item(product: str, location: str, quantity: int = 1, product_type: str = "Ascend Product"):
	"""Remove the given quantity of a product from a Warehouse Location's on-hand inventory.

	Decrements the matching Location Inventory row, removing it entirely once it reaches
	zero. Throws if the location has no on-hand quantity of the product or if the
	requested quantity exceeds what is on hand there.
	"""
	quantity = cint(quantity)
	if quantity <= 0:
		frappe.throw("Quantity must be greater than zero.")

	product_type, product = effective_product(product_type, product)
	warehouse_location = frappe.get_doc("Warehouse Location", location)
	existing_row = _get_inventory_row(warehouse_location, product, product_type)

	if not existing_row:
		frappe.throw(f"{location} has no on-hand quantity of {product}.")

	on_hand = cint(existing_row.quantity)
	if quantity > on_hand:
		frappe.throw(
			f"Cannot check out {quantity}: only {on_hand} of {product} on hand at {location}."
		)

	if quantity == on_hand:
		warehouse_location.remove(existing_row)
	else:
		existing_row.quantity = on_hand - quantity

	warehouse_location.save()
	return warehouse_location.name
