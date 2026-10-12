# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Resolve a scanned barcode or typed identifier to a product Bullwheel can print, tag or shelve.

A product is either an Ascend Product or a New Product still waiting to be imported into Ascend.
Scan-driven screens (Swap Tag Batch, the Swap Tag scan block, warehouse check-in and Find
Product) cannot know in advance which one a barcode belongs to, so they call
`resolve_scanned_product`, which prefers the live Ascend Product and falls back to the staged
New Product — and, once a New Product has been matched to Ascend, to its Ascend Product.
"""

import frappe

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct

ASCEND_PRODUCT = "Ascend Product"
NEW_PRODUCT = "New Product"


def effective_product(doctype: str, name: str) -> tuple[str, str]:
	"""The (doctype, name) a stored product reference should be read through. A New Product that
	has been matched to its Ascend Product reads through that Ascend Product, so a reference saved
	before the match (a bay row, a swap batch row) keeps showing live Ascend data and prices."""
	if doctype == NEW_PRODUCT:
		ascend_product = frappe.db.get_value(NEW_PRODUCT, name, "ascend_product")
		if ascend_product:
			return ASCEND_PRODUCT, ascend_product
	return doctype, name


@frappe.whitelist()
def resolve_scanned_product(identifier: str) -> dict | None:
	"""Resolve a scanned identifier to {doctype, name, description, upc}, or None when nothing
	matches. Checks the Ascend Product first (by Store SKU or UPC), then a New Product not
	cancelled (by UPC or VPN); a New Product already matched to Ascend resolves to its Ascend
	Product."""
	identifier = (identifier or "").strip()
	if not identifier:
		return None

	if product := AscendProduct.get_values(identifier, ["name", "description", "upc"]):
		return {"doctype": ASCEND_PRODUCT, "name": product.name, "description": product.description, "upc": product.upc}

	matches = frappe.get_all(
		NEW_PRODUCT,
		filters={"status": ["!=", "Cancelled"]},
		or_filters=[["upc", "=", identifier], ["vpn", "=", identifier]],
		fields=["name", "description", "upc", "ascend_product"],
		order_by="creation asc",
		limit=1,
	)
	if not matches:
		return None

	new_product = matches[0]
	if new_product.ascend_product:
		if product := AscendProduct.get_values(new_product.ascend_product, ["name", "description", "upc"]):
			return {"doctype": ASCEND_PRODUCT, "name": product.name, "description": product.description, "upc": product.upc}

	return {
		"doctype": NEW_PRODUCT, "name": new_product.name,
		"description": new_product.description, "upc": new_product.upc,
	}
