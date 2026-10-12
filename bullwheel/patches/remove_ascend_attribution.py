# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Bullwheel no longer writes to Ascend, so the machinery that attributed those writes to an
Ascend user is gone: the Ascend User DocType, the User form's Ascend Integration section, and
Bullwheel Settings' default_user / default_location. Fixtures never delete rows that were
removed from the app, so the two User Custom Fields are deleted here explicitly."""

import frappe


def execute():
	for custom_field in ("User-ascend_user", "User-ascend_integration_section"):
		if frappe.db.exists("Custom Field", custom_field):
			frappe.delete_doc("Custom Field", custom_field, force=True, ignore_permissions=True)

	if frappe.db.exists("DocType", "Ascend User"):
		frappe.delete_doc("DocType", "Ascend User", force=True, ignore_permissions=True)
