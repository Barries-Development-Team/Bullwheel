# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt


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


@frappe.whitelist()
def get_swap_prices(products):
	"""Return the current Ski Swap Price for each of the given Ascend Product names in one query, as {product: price_or_None}."""
	if isinstance(products, str):
		products = json.loads(products)
	products = list(dict.fromkeys(products))
	if not products:
		return {}

	rows = frappe.get_all(
		"Product Price",
		filters={"pricing_type": "Ski Swap Price", "product": ["in", products]},
		fields=["product", "price"],
	)
	prices = {row.product: row.price for row in rows}
	return {product: prices.get(product) for product in products}


@frappe.whitelist()
def set_swap_prices(prices):
	"""Upsert the Ski Swap Price for each product in {product: price}, updating the existing Product Price record when one exists and inserting a new one otherwise."""
	if isinstance(prices, str):
		prices = json.loads(prices)
	if not prices:
		return

	for product, price in prices.items():
		price_name = f"PRICE-SWAP-{product}"
		if frappe.db.exists("Product Price", price_name):
			frappe.db.set_value("Product Price", price_name, "price", flt(price))
		else:
			frappe.get_doc(
				{
					"doctype": "Product Price",
					"product": product,
					"pricing_type": "Ski Swap Price",
					"price": flt(price),
				}
			).insert()
