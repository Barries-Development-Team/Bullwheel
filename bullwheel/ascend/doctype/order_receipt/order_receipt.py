# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import json
import re

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core import get_default_ascend_database
from bullwheel.ascend.doctype.vendor_product.vendor_product import VendorProduct, create_vendor_product
from bullwheel.ascend.doctype.vendor.vendor import Vendor
from bullwheel.ascend.import_sheets import build_import_sheet, serve_file_download


class OrderReceipt(Document):

	def validate(self):
		if not self.cached_vendor_id:
			vendor_record = Vendor.get_cached_value(name=self.vendor, fields=['id'])
			if not vendor_record:
				frappe.throw(f'Vendor "{self.vendor}" was not found in Ascend.')
			self.cached_vendor_id = vendor_record.id

	@property
	def total_order_items(self):
		total = 0
		for item in self.order_items:
			total += item.quantity or 0
		return total

	@property
	def subtotal(self):
		total = 0
		for item in self.order_items:
			total += (item.quantity or 0) * (item.cost or 0)
		return total
	
	@property
	def order_total(self):
		if self.shipping_charges is None:
			return self.subtotal
		return self.subtotal + self.shipping_charges

def populate_item_snapshot(row):
	"""Snapshot the linked Vendor Product's description/upc onto an order item at add/edit
	time, so they are stored (not re-derived from Ascend on every load). Skips the lookup
	when description/upc are already set (e.g. supplied by the scan flow). During the
	receiving flow's vendor-link/new-product window, an item may briefly reference a Vendor
	Product that does not exist in Ascend yet; get_values returns None then and this is a
	no-op, leaving the caller-supplied snapshot values in place."""

	if not row.vpn or (row.description and row.upc):
		return

	values = VendorProduct.get_values(row.vpn, ["description", "upc"])

	if values:
		row.description = values.get("description")
		row.upc = values.get("upc")

def child_doctype_for_table(table):
	"""Return the child DocType of the given Order Receipt table field, throwing if `table`
	is not actually a child table on Order Receipt. This bounds the whitelisted `table`
	argument to real child tables (order_items)."""

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
			row = doc.append(table, values)
		case 'edit':
			row = find_row(doc, table, row_name)
			row.update(values)
		case 'remove':
			doc.remove(find_row(doc, table, row_name))
			row = None

	# Snapshot the product's description/upc once, here, so loads never re-query Ascend.
	if row is not None and table == 'order_items':
		row.description = row.upc = None  # force a fresh snapshot in case vpn changed
		populate_item_snapshot(row)

	# Links are validated upstream (dialog Dynamic Link / scan_item); skip the per-row
	# Ascend round-trips that _validate_links would otherwise make on every save.
	doc.flags.ignore_links = True
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

def add_or_increment_item(docname, vpn, cost=None, description=None, upc=None):
	"""Add an order item for the given Vendor Product, or bump its quantity if an unreceived row
	for the same vpn already exists. Rows already marked received are treated as read-only
	history from a prior batch and are never matched, so a new row is appended instead. Used
	by the scan flow; runs under the row lock so concurrent scans serialize instead of racing.
	description/upc are supplied by the caller (scan_item or the vendor-link/new-product flows
	already have them), so the snapshot needs no extra Ascend query."""

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)

	existing = next((row for row in doc.order_items if row.vpn == vpn and not row.received), None)
	if existing:
		existing.quantity += 1
	else:
		row = doc.append("order_items", {
			"vpn": vpn,
			"quantity": 1,
			"cost": cost,
			"description": description,
			"upc": upc,
		})
		populate_item_snapshot(row)  # no-op when the caller already supplied description/upc

	doc.flags.ignore_links = True
	doc.save()
	frappe.db.commit()

@frappe.whitelist()
def queue_add_or_increment_item(docname, vpn, cost=None, description=None, upc=None):
	"""Enqueue a serialized add-or-increment of an order item (scan flow)."""

	frappe.enqueue(
		method='bullwheel.ascend.doctype.order_receipt.order_receipt.add_or_increment_item',
		queue='short',
		enqueue_after_commit=True,
		now=False,
		is_async=True,
		at_front=False,
		docname=docname,
		vpn=vpn,
		cost=cost,
		description=description,
		upc=upc,
	)

@frappe.whitelist()
def scan_item(id: str, vendor: str, cached_vendor_id: str):
	"""Resolve a scanned identifier to an item this order can receive. Checks, in order: a
	Vendor Product in Ascend for this vendor, then any Product in Ascend. Returns a
	(status, record) tuple; status is one of 'vpn found', 'product found', or 'not found'."""

	if not cached_vendor_id:
		frappe.throw('Order Receipt has no cached vendor ID. Re-save the document to populate it.')

	# Determine if Vendor Product exists for the scanned item.

	vpn_query = ('SELECT VP.PartNumber as vpn, VP.Cost as cost, P.Description as description, P.UPC as upc  '
			'FROM VendorProducts as VP '
			'JOIN Products as P ON VP.ProductID = P.ID '
			'WHERE VP.VendorID = %s AND (P.UPC = %s OR P.[Store UPC] = %s OR P.MfgrPartNo = %s)'
	)

	values = [cached_vendor_id, id, id, id]

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
		
		# Determine if Product exists for the scanned item. Custom lookup is used instead of virtual doctype methods to avoid reestablishing database connection.

		product_query = ('SELECT ID as product_id, [Store UPC] as store_sku, UPC as upc, '
			'Description as description, EstCost as cost, MfgrPartNo as mpn, Brand as brand, '
			'Color as color, StyleName as style_name, Size as size '
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


@frappe.whitelist()
def link_vendor_product(docname, product_id, part_number, cost, description=None, upc=None):
	"""Create the missing Ascend Vendor Product linking this receipt's vendor to an existing
	Ascend Product, then add or increment the matching order item. Runs synchronously (not
	enqueued), unlike the other mutation entry points, so a failed Ascend insert surfaces
	directly in the caller's vendor-link dialog instead of failing silently in a background
	job; the receipt mutation itself still goes through add_or_increment_item's row lock."""

	receipt = frappe.db.get_value("Order Receipt", docname, ["vendor", "cached_vendor_id"], as_dict=True)
	if not receipt or not receipt.vendor:
		frappe.throw(f'Order Receipt "{docname}" has no vendor set.')
	if not receipt.cached_vendor_id:
		frappe.throw(f'Order Receipt "{docname}" has no cached vendor ID. Re-save the document to populate it.')

	vendor = receipt.vendor

	create_vendor_product(
		vendor_id=receipt.cached_vendor_id,
		product_id=product_id,
		part_number=part_number,
		cost=cost,
		description=description,
	)

	vendor_product_name = f"{part_number} ({vendor})"  # matches VendorProduct.NAME_EXPRESSION
	add_or_increment_item(docname, vendor_product_name, cost=cost, description=description, upc=upc)
	return vendor_product_name


def _import_template_path(filename):
	"""Absolute path to an Ascend import template shipped with the app."""
	return frappe.get_app_path("bullwheel", "ascend", "import_templates", filename)


# A vendor display name is the final parenthesized group, preceded by whitespace:
# "<part number> (<vendor>)". Anchored to end-of-string so any parentheses inside the
# part number itself are left untouched.
_VENDOR_SUFFIX_PATTERN = re.compile(r"\s+\([^()]*\)$")


def _resolve_ascend_vpn(item):
	"""The bare Ascend VPN for a PO line. An order item's `vpn` carries the Vendor Product's
	docname, "<part> (<vendor>)", so strip the trailing vendor suffix down to the part
	number Ascend expects."""

	return _VENDOR_SUFFIX_PATTERN.sub("", item.vpn)


def _order_item_to_po_row(item):
	"""Project one order item onto the Ascend Vendor Order (PO) template column headers."""

	return {
		"Identifier": _resolve_ascend_vpn(item),
		"Description": item.description,
		"Qty": item.quantity,
		"Cost": item.cost,
		"Comments": item.comments,
	}


def _mark_items_received(docname):
	"""Flag every order item on the receipt as received, inside a row lock so it serializes
	with concurrent receiving edits. Called once the export sheet has built successfully."""

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)
	for item in doc.order_items:
		item.received = 1

	doc.flags.ignore_links = True
	doc.save()
	frappe.db.commit()


@frappe.whitelist()
def export_received_batch(docname):
	"""Build the Ascend PO import sheet for a received order from `order_items`, then mark
	the order's items as received. Vendor Products are now created directly in Ascend during
	receiving (see link_vendor_product / the New Product creation flow), so there is no
	longer a separate Vendor Products sheet to export."""

	doc = frappe.get_doc("Order Receipt", docname)

	po_sheet = build_import_sheet(
		_import_template_path("ascend_template_purchase_order.xlsx"),
		[_order_item_to_po_row(item) for item in doc.order_items],
	)

	# Only mark received once the sheet has built, so a failure never silently receives the batch.
	_mark_items_received(docname)

	serve_file_download(
		f"PO - {docname}.xlsx",
		po_sheet,
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	)