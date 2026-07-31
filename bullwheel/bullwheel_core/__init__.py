# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe

from bullwheel.bullwheel_core.exceptions import *


def print_console_warning(message: str):
    """Print a warning message to the console in yellow."""
    print(f"\033[33m{message}\033[0m")


def get_default_ascend_database():
		try:
			if cached_default_database := frappe.cache.get_value('default_ascend_database'):
				default_database = cached_default_database
			else:
				default_database = frappe.db.get_value('Bullwheel Settings', 'default_database')
				frappe.cache.set_value('default_ascend_database', default_database, expires_in_sec=30) # Ensures that default database changes are applied quickly.

			return frappe.get_cached_doc("SQL Server", default_database)
		except:
			raise AscendDatabaseNotConfigured

def get_label(slot):
	"""Return the Zebra Printer Label configured for a Bullwheel Settings label slot
	(e.g. 'warehouse_location'), raising PrintLabelNotConfigured if the slot is unset."""
	label_name = frappe.db.get_single_value('Bullwheel Settings', slot)
	if not label_name:
		raise PrintLabelNotConfigured
	return frappe.get_doc("Zebra Printer Label", label_name)

def ski_category_prefix(bootinfo):
	"""Expose the configured Ski Category Prefix to the desk client (wired via the
	extend_bootinfo hook). New Product's ski-detail fields gate their visibility, and Binding
	Brand and Model its required-ness, off frappe.boot.ski_category_prefix via
	depends_on/mandatory_depends_on expressions — which also run in the Quick Entry receiving
	modal, where form scripts do not, so this is how the same Bullwheel Settings prefix the
	server uses reaches that modal without being hardcoded."""
	bootinfo.ski_category_prefix = frappe.db.get_single_value('Bullwheel Settings', 'ski_category_prefix')