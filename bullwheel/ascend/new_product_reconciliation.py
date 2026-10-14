# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Match imported New Products to the Ascend records Ascend created from them.

Bullwheel cannot write to Ascend, so a New Product waits in Bullwheel until staff import its
Vendor Products sheet. After the import, Ascend holds a Vendor Product named "<VPN> (<vendor>)" —
the same name Bullwheel gave the New Product — pointing at the Ascend Product. This module finds
those Vendor Products, ties each New Product to its Ascend Product (which also hands over the Store
SKU Ascend assigned), creates Bullwheel's own Product Price / Ski with Bindings records for it, and
repoints warehouse bay rows and swap tag batch rows from the New Product to the Ascend Product.

Runs on a schedule (hooks.py) and from the Check Ascend buttons.
"""

import frappe

from bullwheel.ascend.doctype.vendor_product.vendor_product import VendorProduct

# New Products that may have been imported: waiting on, or never marked as, an export.
MATCHABLE_STATUSES = ["Pending", "Exported"]

# (doctype, product link field, product type field) of the Bullwheel records that point at a
# product by (type, name) and move to the Ascend Product once there is one. Order Receipt Items
# are deliberately absent: they keep pointing at the New Product, whose label/PO resolution
# already follows ascend_product.
REPOINTED_REFERENCES = (
	("Location Inventory", "product", "product_type"),
	("Swap Tag Batch Item", "product", "product_type"),
)


def vendor_product_name(new_product) -> str:
	"""The name Ascend's Vendor Product gets once this New Product is imported: VendorProduct's
	NAME_EXPRESSION, '<part number> (<vendor>)'."""
	return f"{new_product.vpn} ({new_product.vendor})"


def adopt_imported_base_products() -> int:
	"""Existing Product entries that refer to a pending New Product pick up that product's Ascend
	Product as soon as it has one (saving runs New Product's source-copying validation, which
	adopts it). Returns how many entries were updated."""
	waiting = frappe.get_all(
		"New Product",
		filters={
			"entry_type": "Existing Product", "base_new_product": ["is", "set"],
			"ascend_product": ["is", "not set"], "status": ["!=", "Cancelled"],
		},
		fields=["name", "base_new_product"],
	)

	adopted = 0
	for entry in waiting:
		if not frappe.db.get_value("New Product", entry.base_new_product, "ascend_product"):
			continue
		document = frappe.get_doc("New Product", entry.name)
		document.flags.ignore_lock = True
		document.save()
		adopted += 1
	return adopted


def repoint_references(new_product_name: str, store_sku: str) -> None:
	"""Move the warehouse bay rows and swap tag batch rows that point at a New Product onto its
	Ascend Product. A bay that already stores the Ascend Product has the quantities merged into
	the existing row instead of gaining a duplicate."""
	for doctype, link_field, type_field in REPOINTED_REFERENCES:
		rows = frappe.get_all(
			doctype,
			filters={type_field: "New Product", link_field: new_product_name},
			fields=["name", "parent", "quantity"] if doctype == "Location Inventory" else ["name"],
		)
		for row in rows:
			if doctype == "Location Inventory":
				existing = frappe.db.get_value(
					doctype,
					{"parent": row.parent, type_field: "Ascend Product", link_field: store_sku},
					["name", "quantity"], as_dict=True,
				)
				if existing:
					frappe.db.set_value(doctype, existing.name, "quantity", (existing.quantity or 0) + (row.quantity or 0))
					frappe.db.delete(doctype, {"name": row.name})
					continue

			frappe.db.set_value(
				doctype, row.name, {type_field: "Ascend Product", link_field: store_sku}, update_modified=False
			)


def reconcile_pending_new_products(names=None) -> dict:
	"""Match every Pending/Exported New Product (or just `names`) that Ascend now holds a Vendor
	Product for. Each match is its own transaction, so one failure cannot undo the others; failures
	are logged and reported in the result. Returns {"matched": [...], "waiting": n, "failed": [...]}."""
	result = {"matched": [], "waiting": 0, "failed": []}

	filters = {"status": ["in", MATCHABLE_STATUSES]}
	if names:
		filters["name"] = ["in", names]
	candidates = frappe.get_all(
		"New Product", filters=filters, fields=["name", "vpn", "vendor"], order_by="creation asc"
	)
	if not candidates:
		return result

	found = VendorProduct.get_bulk_values([vendor_product_name(row) for row in candidates], ["product"])

	for candidate in candidates:
		vendor_product = found.get(vendor_product_name(candidate))
		if not vendor_product or not vendor_product.product:
			result["waiting"] += 1
			continue

		try:
			document = frappe.get_doc("New Product", candidate.name)
			document.link_imported_product(vendor_product.product)
			repoint_references(document.name, vendor_product.product)
			frappe.db.commit()
			result["matched"].append(candidate.name)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Could not match New Product {candidate.name} to Ascend")
			result["failed"].append(candidate.name)

	if adopt_imported_base_products():
		frappe.db.commit()

	return result


def scheduled_reconciliation() -> None:
	"""Scheduler entry point. An unreachable Ascend database is logged, not raised, so one
	outage does not mark the scheduled job as crashing every fifteen minutes."""
	try:
		reconcile_pending_new_products()
	except Exception:
		frappe.log_error(title="New Product reconciliation could not reach Ascend")


@frappe.whitelist()
def check_ascend(names=None) -> dict:
	"""Check Ascend for imports of the given New Products (all waiting ones when omitted) and
	report the outcome to the user. Requires permission to edit New Products."""
	frappe.has_permission("New Product", "write", throw=True)
	if isinstance(names, str):
		names = frappe.parse_json(names)

	result = reconcile_pending_new_products(names or None)

	lines = []
	if result["matched"]:
		lines.append(f"Matched to Ascend: {', '.join(result['matched'])}.")
	if result["waiting"]:
		lines.append(f"{result['waiting']} not found in Ascend yet — import their Vendor Products sheet first.")
	if result["failed"]:
		lines.append(f"Could not match: {', '.join(result['failed'])}. See the Error Log.")
	frappe.msgprint(
		"<br>".join(lines) or "Nothing is waiting to be imported.",
		title="Check Ascend",
		indicator="red" if result["failed"] else "green",
	)
	return result
