# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Order Receipt Item gained an item_type (Vendor Product / New Product) that its vpn Dynamic Link
points through. Every row that exists today was added against a Vendor Product. Sites that ran
backfill_order_item_snapshot still carry an orphaned item_type column holding that older design's
values, so this overwrites it unconditionally rather than only filling blanks."""

import frappe


def execute():
	frappe.db.sql("UPDATE `tabOrder Receipt Item` SET `item_type` = 'Vendor Product'")
