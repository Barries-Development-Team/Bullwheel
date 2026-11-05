# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Resolve a scanned barcode or typed identifier to a product Bullwheel can print, tag or shelve.

A product is either an Ascend Product or a New Product still waiting to be imported into Ascend.
Scan-driven screens (Swap Tag Batch, the Swap Tag scan block, warehouse check-in and Find
Product) cannot know in advance which one a barcode belongs to, so they call
`resolve_scanned_product`, which prefers the live Ascend Product and falls back to the staged
New Product — and, once a New Product has been matched to Ascend, to its Ascend Product.
Client-side, screens go through `bullwheel.ascend.resolve_scanned_product` (public/js/utils/
ascend.js), which asks the user to pick when a scan matches several products.
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


PRODUCT_FIELDS = ["name", "description", "upc"]


def _product_result(doctype: str, product) -> dict:
	"""The {doctype, name, description, upc} shape scan screens consume."""
	return {"doctype": doctype, "name": product.name, "description": product.description, "upc": product.upc}


def _single_or_candidates(results: list) -> dict | None:
	"""One product resolves to itself; several equally good matches are returned as
	{"candidates": [...]} for the scan screen to pick from; none resolves to None."""
	if not results:
		return None
	if len(results) == 1:
		return results[0]
	return {"candidates": results}


@frappe.whitelist()
def resolve_scanned_product(identifier: str) -> dict | None:
	"""Resolve a scanned identifier to {doctype, name, description, upc}, or None when nothing
	matches. Checks the Ascend Product first (by Store SKU, then UPC, then vendor part number),
	then a New Product not cancelled (by UPC, then VPN); a New Product already matched to Ascend
	resolves to its Ascend Product. When the identifier matches several products equally well (a
	part number several vendors' products share, a duplicate UPC), returns {"candidates": [...]}
	instead, each in the single-product shape, so the screen can ask which one was meant."""
	identifier = (identifier or "").strip()
	if not identifier:
		return None

	if ascend_products := AscendProduct.find_by_identifier(identifier, PRODUCT_FIELDS):
		return _single_or_candidates([_product_result(ASCEND_PRODUCT, product) for product in ascend_products])

	matches = frappe.get_all(
		NEW_PRODUCT,
		filters={"status": ["!=", "Cancelled"]},
		or_filters=[["upc", "=", identifier], ["vpn", "=", identifier]],
		fields=["name", "description", "upc", "ascend_product"],
		order_by="creation asc",
	)
	# A UPC match beats a VPN match, mirroring the Ascend Product ranking.
	upc_matches = [match for match in matches if (match.upc or "").casefold() == identifier.casefold()]

	results = []
	seen = set()
	for new_product in upc_matches or matches:
		result = None
		if new_product.ascend_product:
			if product := AscendProduct.get_values(new_product.ascend_product, PRODUCT_FIELDS):
				result = _product_result(ASCEND_PRODUCT, product)
		result = result or _product_result(NEW_PRODUCT, new_product)
		if (result["doctype"], result["name"]) not in seen:
			seen.add((result["doctype"], result["name"]))
			results.append(result)

	return _single_or_candidates(results)
