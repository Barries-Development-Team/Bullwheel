# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe

def get_default_ascend_database():
		default_database = frappe.db.get_single_value('Bullwheel Settings', 'default_database')
		return frappe.get_doc("SQL Server", default_database)