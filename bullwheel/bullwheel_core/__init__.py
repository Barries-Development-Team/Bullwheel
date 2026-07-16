# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe

from bullwheel.bullwheel_core.exceptions import *


def print_console_warning(message: str):
    """Print a warning message to the console in yellow."""
    print(f"\033[33m{message}\033[0m")

def get_default_ascend_database():
		try:
			default_database = frappe.db.get_single_value('Bullwheel Settings', 'default_database')
			return frappe.get_doc("SQL Server", default_database)
		except:
			raise AscendDatabaseNotConfigured

def get_label(slot):
	"""Return the Zebra Printer Label configured for a Bullwheel Settings label slot
	(e.g. 'warehouse_location'), raising PrintLabelNotConfigured if the slot is unset."""
	label_name = frappe.db.get_single_value('Bullwheel Settings', slot)
	if not label_name:
		raise PrintLabelNotConfigured
	return frappe.get_doc("Zebra Printer Label", label_name)