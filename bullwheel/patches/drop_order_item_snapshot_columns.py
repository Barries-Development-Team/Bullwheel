# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""description/upc on Order Receipt Item moved back to is_virtual — computed via a short-TTL
Ascend cache (see AbstractVirtualDocType.get_bulk_short_cached_values) — instead of the stored
snapshot populate_item_snapshot used to write. Frappe never drops a MariaDB column just because
a field's is_virtual flag changed, and leaving these two orphaned is not just inert: Frappe's
list-view/report SQL builder (frappe/model/db_query.py) only special-cases is_virtual at the
whole-DocType level, not per field, so any future frappe.get_all/get_value/report query against
these fieldnames would silently read the frozen pre-migration snapshot straight out of the
orphaned column instead of computing (or erroring on) the live value. Dropping the columns turns
that into a loud, immediate SQL error instead.
"""

import frappe


def execute():
	for column in ("description", "upc"):
		if frappe.db.has_column("Order Receipt Item", column):
			frappe.db.sql_ddl(f"ALTER TABLE `tabOrder Receipt Item` DROP COLUMN `{column}`")
