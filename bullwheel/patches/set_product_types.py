# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Location Inventory and Swap Tag Batch Item rows can now point at a New Product that is still
waiting to be imported into Ascend, so each carries a product_type its product Dynamic Link reads.
Every row that exists today points at an Ascend Product."""

import frappe


def execute():
	for doctype in ("Location Inventory", "Swap Tag Batch Item"):
		frappe.db.sql(
			f"UPDATE `tab{doctype}` SET `product_type` = 'Ascend Product' "
			"WHERE `product_type` IS NULL OR `product_type` = ''"
		)
