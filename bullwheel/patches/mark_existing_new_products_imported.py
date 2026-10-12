# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Until now creating a New Product also created its Ascend Product (named by the New Product's
Store SKU), so every existing New Product is already in Ascend. Under the new lifecycle a New
Product means "waiting to be imported", so each existing record must be marked Imported and
linked to its Ascend Product — otherwise it would show as Pending and be exported a second time,
creating a duplicate in Ascend.

A record whose Ascend Product cannot be found was never completed in Ascend (the old write could
fail after the Bullwheel row committed), so it is left Pending to be exported normally. If Ascend
is unreachable this raises, blocking the migration: guessing here would silently duplicate or
orphan records."""

import frappe

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct


def execute():
	names = frappe.get_all("New Product", pluck="name")
	if not names:
		return

	found = AscendProduct.get_bulk_values(names, ["id"])

	for name in names:
		if name in found:
			frappe.db.set_value(
				"New Product", name,
				{
					"status": "Imported",
					"entry_type": "New Product",
					"ascend_product": name,
					"store_sku": name,
				},
				update_modified=False,
			)
		else:
			frappe.db.set_value("New Product", name, "entry_type", "New Product", update_modified=False)
			print(f"New Product {name} is not in Ascend; left Pending so it is exported normally.")
