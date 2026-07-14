# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database
from bullwheel.ascend.doctype.vendor.vendor import Vendor


class OrderReceipt(Document):
	pass

def child_doctype_for_table(table):
	"""Return the child DocType of the given Order Receipt table field, throwing if `table`
	is not actually a child table on Order Receipt. This bounds the whitelisted `table`
	argument to real child tables (order_items, new_products)."""

	field = frappe.get_meta("Order Receipt").get_field(table)
	if not field or field.fieldtype != "Table":
		frappe.throw(f'"{table}" is not a child table of Order Receipt.')
	return field.options

def writable_fieldnames(table):
	"""Fieldnames on the table's child DocType that a user may set: value-bearing, not
	read-only, not virtual. Derived from the DocType meta so the allowlist stays in sync
	with the DocType definition (virtual/read-only fields are excluded automatically)."""

	return {
		field.fieldname
		for field in frappe.get_meta(child_doctype_for_table(table)).fields
		if not field.read_only and not field.is_virtual and field.fieldtype not in frappe.model.no_value_fields
	}

def lock_row(docname):
	"""Take an exclusive row lock on this Order Receipt (SELECT ... FOR UPDATE) so that
	concurrent jobs editing the same receipt's child tables serialize instead of racing
	and losing each other's updates. ALWAYS call this before reading the doc you will modify."""

	frappe.db.sql(
        "SELECT `name` FROM `tabOrder Receipt` WHERE `name`=%s FOR UPDATE",
        docname,
    )

def find_row(doc, table, row_name):
	"""Return the child row named row_name from the given child table, or throw if it is
	missing (e.g. another job already removed it)."""

	for row in doc.get(table):
		if row.name == row_name:
			return row

	frappe.throw(f'Row "{row_name}" was not found in "{table}".')

def clean_values(table, values):
	"""Reduce a raw values dict to only the fields writable on the table's child DocType."""

	allowed = writable_fieldnames(table)
	return {field: values[field] for field in values if field in allowed}

def update_table(docname, table, job, values=None, row_name=None):
	"""Apply a single add/edit/remove operation to a child table of an Order Receipt inside a
	row lock, so simultaneous receiving edits are serialized. Runs as an enqueued job; the job
	runner handles rollback on error, so we only commit on success."""

	if job not in ['add', 'edit', 'remove']:
		raise ValueError('Incorrect job argument. Valid arguments are "add", "edit", and "remove".')

	if isinstance(values, str):
		values = json.loads(values or '{}')
	values = clean_values(table, values or {})

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)

	match job:
		case 'add':
			doc.append(table, values)
		case 'edit':
			find_row(doc, table, row_name).update(values)
		case 'remove':
			doc.remove(find_row(doc, table, row_name))

	doc.save()
	frappe.db.commit()

@frappe.whitelist()
def queue_update_table(docname, table, job, values=None, row_name=None):
	"""Enqueue a serialized add/edit/remove against an Order Receipt child table."""

	kwargs = {
		'docname': docname,
		'table': table,
		'job': job,
		'values': values,
		'row_name': row_name,
	}

	frappe.enqueue(
		method = 'bullwheel.ascend.doctype.order_receipt.order_receipt.update_table',
		queue = 'short',
		enqueue_after_commit = True,
		now = False,
		is_async = True,
		at_front = False,
		**kwargs
	)
	
@frappe.whitelist()
def scan_item(id: str, vendor: str):
	"""Determine existance of a Vendor Product for the scanned item, and return the Vendor Product's VPN if it exists.
	If the VPN does not exist, determine if a Product exists for the scanned item and return the Product's Store SKU."""

	# Determine if Vendor Product exists for the scanned item.

	vpn_query = ('SELECT VP.PartNumber as vpn, VP.Cost as cost, P.Description as description, P.UPC as upc  '
			'FROM VendorProducts as VP '
			'JOIN Products as P ON VP.ProductID = P.ID '
			'WHERE VP.VendorID = (SELECT ID FROM Vendors WHERE Name = %s) AND (P.UPC = %s OR P.[Store UPC] = %s OR P.MfgrPartNo = %s)'
	)

	values = [vendor, id, id, id]

	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		result = ascend.sql(
			query=vpn_query,
			values=values,
			as_dict=True
		)

		if len(result) > 0:
			record = result[0]
			vendor_product_name = f"{result[0]['vpn']} ({vendor})" # e.g. "12345 (Barrie's Ski and Sports)"
			record['vpn'] = vendor_product_name
			return ('vpn found', record)
		
		# Determine if Product exists for the scanned item.

		product_query = ('SELECT [Store UPC] as store_sku, UPC as upc, Description as description, EstCost as cost '
			'FROM Products '
			'WHERE UPC = %s OR [Store UPC] = %s OR MfgrPartNo = %s'
		)

		values = [id, id, id]

		result = ascend.sql(
			query=product_query,
			values=values,
			as_dict=True
		)

		if len(result) > 0:
			return ('product found', result[0])
		
		return ('not found', None)