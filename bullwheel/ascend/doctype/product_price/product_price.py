# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from bullwheel.ascend.product_lookup import ASCEND_PRODUCT, NEW_PRODUCT, effective_product


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


def _product_references(products) -> list[tuple[tuple[str, str], tuple[str, str]]]:
	"""Normalize the `products` argument of the swap price endpoints into unique
	((requested doctype, name), (effective doctype, name)) pairs, the effective one being read
	through effective_product. Accepts a bare list of Ascend Product names, or a list of
	{doctype, name} dicts (a New Product may be waiting for import)."""
	if isinstance(products, str):
		products = json.loads(products)

	references = []
	for product in products or []:
		doctype, name = (
			(product.get("doctype") or ASCEND_PRODUCT, product.get("name"))
			if isinstance(product, dict) else (ASCEND_PRODUCT, product)
		)
		if name:
			references.append(((doctype, name), effective_product(doctype, name)))
	return list(dict.fromkeys(references))


@frappe.whitelist()
def get_swap_prices(products):
	"""Return the current Ski Swap Price for each product in one pass, as {name: price_or_None},
	keyed by the name that was asked for. An Ascend Product's price is its Product Price record; a
	New Product waiting for import keeps its price on the New Product itself."""
	references = _product_references(products)
	if not references:
		return {}

	effective = [effective_reference for _, effective_reference in references]
	ascend_names = [name for doctype, name in effective if doctype == ASCEND_PRODUCT]
	new_product_names = [name for doctype, name in effective if doctype == NEW_PRODUCT]

	prices = {name: None for _, name in effective}
	if ascend_names:
		for row in frappe.get_all(
			"Product Price",
			filters={"pricing_type": "Ski Swap Price", "product": ["in", ascend_names]},
			fields=["product", "price"],
		):
			prices[row.product] = row.price
	if new_product_names:
		for row in frappe.get_all(
			NEW_PRODUCT, filters={"name": ["in", new_product_names]}, fields=["name", "swap_price"]
		):
			prices[row.name] = row.swap_price or None
	return {requested_name: prices[effective_name] for (_, requested_name), (_, effective_name) in references}


@frappe.whitelist()
def set_swap_prices(prices):
	"""Upsert the Ski Swap Price for each product. `prices` is a list of {doctype, name, price}
	(or a bare {ascend product name: price} dict). An Ascend Product's price updates its existing
	Product Price record, inserting one when none exists; a New Product waiting for import has the
	price written to the New Product itself — directly, so its pricing rule does not recompute it."""
	if isinstance(prices, str):
		prices = json.loads(prices)
	if not prices:
		return

	if isinstance(prices, dict):
		prices = [{"doctype": ASCEND_PRODUCT, "name": name, "price": price} for name, price in prices.items()]

	for entry in prices:
		doctype, name = effective_product(entry.get("doctype") or ASCEND_PRODUCT, entry["name"])
		price = flt(entry["price"])

		if doctype == NEW_PRODUCT:
			frappe.db.set_value(NEW_PRODUCT, name, "swap_price", price)
			continue

		price_name = f"PRICE-SWAP-{name}"
		if frappe.db.exists("Product Price", price_name):
			frappe.db.set_value("Product Price", price_name, "price", price)
		else:
			frappe.get_doc(
				{
					"doctype": "Product Price",
					"product": name,
					"pricing_type": "Ski Swap Price",
					"price": price,
				}
			).insert()
