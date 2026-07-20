# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Backfill the newly-stored description/upc snapshot on existing Order Receipt Item rows.

These fields used to be virtual (re-derived from Ascend on every load, the receiving-job
performance bottleneck). After converting them to stored fields, existing rows are empty, so
populate them once here: Vendor Product rows from Ascend (batched), New Product rows from the
local New Product record. Written via db.set_value to avoid re-saving/re-validating parents.
"""

import frappe


def _chunks(items, size):
	for start in range(0, len(items), size):
		yield items[start:start + size]


def execute():
	# Order Receipt Item no longer carries item_type (it now only links to Vendor Product), so
	# a fresh site has no such column to backfill. Sites where this patch already ran keep the
	# orphaned column (Frappe never drops removed columns) and have the patch recorded anyway.
	if not frappe.db.has_column("Order Receipt Item", "item_type"):
		return

	rows = frappe.get_all(
		"Order Receipt Item",
		filters={"parentfield": "order_items"},
		fields=["name", "item_type", "vpn", "description", "upc"],
	)
	todo = [row for row in rows if row.vpn and not (row.description and row.upc)]
	if not todo:
		return

	lookup = {}

	# New Product rows — local MariaDB, always available.
	new_product_vpns = sorted({row.vpn for row in todo if row.item_type == "New Product"})
	for chunk in _chunks(new_product_vpns, 200):
		for record in frappe.get_all("New Product", filters={"name": ["in", chunk]},
				fields=["name", "description", "upc"]):
			lookup[record.name] = record

	# Vendor Product rows — Ascend SQL Server (virtual). Guard against it being unreachable
	# during migration so the patch (and New Product backfill) still completes.
	vendor_vpns = sorted({row.vpn for row in todo if row.item_type == "Vendor Product"})
	for chunk in _chunks(vendor_vpns, 50):
		try:
			for record in frappe.get_all("Vendor Product", filters={"name": ["in", chunk]},
					fields=["name", "description", "upc"]):
				lookup[record.name] = record
		except Exception:
			frappe.log_error(title="backfill_order_item_snapshot: Vendor Product lookup failed")

	updated = 0
	for row in todo:
		record = lookup.get(row.vpn)
		if not record:
			continue
		frappe.db.set_value(
			"Order Receipt Item", row.name,
			{"description": record.get("description"), "upc": record.get("upc")},
			update_modified=False,
		)
		updated += 1

	frappe.db.commit()
	print(f"backfill_order_item_snapshot: updated {updated} of {len(todo)} order items")
