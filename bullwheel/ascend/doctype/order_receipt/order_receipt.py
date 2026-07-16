# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import io
import json
import re
import zipfile

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core import get_default_ascend_database
from bullwheel.ascend.doctype.vendor_product.vendor_product import VendorProduct
from bullwheel.ascend.doctype.new_product.new_product import to_import_row
from bullwheel.ascend.import_sheets import build_import_sheet, serve_file_download


class OrderReceipt(Document):
	@property
	def total_order_items(self):
		total = 0
		for item in self.order_items:
			total += item.quantity
		return total
	
	@property
	def subtotal(self):
		total = 0
		for item in self.order_items:
			total += item.quantity * item.cost
		return total
	
	@property
	def order_total(self):
		if self.shipping_charges is None:
			return self.subtotal
		return self.subtotal + self.shipping_charges

def populate_item_snapshot(row):
	"""Snapshot the linked product's description/upc onto an order item at add/edit time, so
	they are stored (not re-derived from Ascend on every load). Vendor Product rows read from
	Ascend once here; New Product rows read from the local New Product record. Skips the lookup
	when description/upc are already set (e.g. supplied by the scan flow)."""

	if not row.vpn or (row.description and row.upc):
		return

	if row.item_type == "Vendor Product":
		values = VendorProduct.get_values(row.vpn, ["description", "upc"])
	else:
		values = frappe.db.get_value("New Product", row.vpn, ["description", "upc"], as_dict=True)

	if values:
		row.description = values.get("description")
		row.upc = values.get("upc")

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

def add_or_increment_item(docname, item_type, vpn, cost=None, description=None, upc=None):
	"""Add an order item for the given vendor/new product, or bump its quantity if a row for
	the same item (matching item_type + vpn) already exists. Used by the scan flow; runs under
	the row lock so concurrent scans serialize instead of racing. description/upc are supplied
	by the scan (scan_item already fetched them), so the snapshot needs no extra Ascend query."""

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)

	existing = next((row for row in doc.order_items if row.item_type == item_type and row.vpn == vpn), None)
	if existing:
		existing.quantity += 1
	else:
		row = doc.append("order_items", {
			"item_type": item_type,
			"vpn": vpn,
			"quantity": 1,
			"cost": cost,
			"description": description,
			"upc": upc,
		})
		populate_item_snapshot(row)  # no-op when the scan already supplied description/upc

	doc.flags.ignore_links = True
	doc.save()
	frappe.db.commit()

@frappe.whitelist()
def queue_add_or_increment_item(docname, item_type, vpn, cost=None, description=None, upc=None):
	"""Enqueue a serialized add-or-increment of an order item (scan flow)."""

	frappe.enqueue(
		method='bullwheel.ascend.doctype.order_receipt.order_receipt.add_or_increment_item',
		queue='short',
		enqueue_after_commit=True,
		now=False,
		is_async=True,
		at_front=False,
		docname=docname,
		item_type=item_type,
		vpn=vpn,
		cost=cost,
		description=description,
		upc=upc,
	)

def stage_new_product(docname, values):
	"""Create a New Product row from `values` and link an order item to it, in one locked
	transaction. The New Product is saved first so its generated name can be used as the
	order item's Dynamic Link target, then the linked order item is appended and saved."""

	if isinstance(values, str):
		values = json.loads(values or '{}')
	values = clean_values('new_products', values or {})

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)

	new_product_row = doc.append("new_products", values)
	doc.flags.ignore_links = True
	doc.save()  # assigns the New Product row its name

	# Snapshot description/upc straight from the New Product we just created — no extra query.
	doc.append("order_items", {
		"item_type": "New Product",
		"vpn": new_product_row.name,
		"quantity": 1,
		"cost": new_product_row.cost,
		"description": new_product_row.description,
		"upc": new_product_row.upc,
	})
	doc.flags.ignore_links = True
	doc.save()
	frappe.db.commit()

@frappe.whitelist()
def queue_stage_new_product(docname, values):
	"""Enqueue serialized New-Product staging (New Product row + linked order item)."""

	frappe.enqueue(
		method='bullwheel.ascend.doctype.order_receipt.order_receipt.stage_new_product',
		queue='short',
		enqueue_after_commit=True,
		now=False,
		is_async=True,
		at_front=False,
		docname=docname,
		values=values,
	)

def find_staged_new_product(docname, id):
	"""Return a New Product already staged on this order whose UPC / MPN / case UPC matches the
	scanned id, or None. Lets a re-scanned item reference the existing New Product instead of
	re-querying Ascend or staging a duplicate."""

	matches = frappe.get_all(
		"New Product",
		filters={"parenttype": "Order Receipt", "parent": docname, "parentfield": "new_products"},
		or_filters={"upc": id, "mpn": id, "case_upc": id},
		fields=["name", "description", "cost", "upc"],
		limit=1,
	)
	return matches[0] if matches else None

@frappe.whitelist()
def scan_item(id: str, vendor: str, docname: str):
	"""Resolve a scanned identifier to an item this order can receive. Checks, in order: a New
	Product already staged on this order, then a Vendor Product in Ascend, then any Product in
	Ascend. Returns a (status, record) tuple; status is one of 'new product found', 'vpn found',
	'product found', or 'not found'."""

	# Check whether this item is already staged as a New Product for this order; if so,
	# reference it instead of querying Ascend or staging a duplicate.
	staged_new_product = find_staged_new_product(docname, id)
	if staged_new_product:
		return ('new product found', staged_new_product)

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


def _import_template_path(filename):
	"""Absolute path to an Ascend import template shipped with the app."""
	return frappe.get_app_path("bullwheel", "ascend", "import_templates", filename)


# A vendor display name is the final parenthesized group, preceded by whitespace:
# "<part number> (<vendor>)". Anchored to end-of-string so any parentheses inside the
# part number itself are left untouched.
_VENDOR_SUFFIX_PATTERN = re.compile(r"\s+\([^()]*\)$")


def _resolve_ascend_vpn(item):
	"""The bare Ascend VPN for a PO line. New-product rows carry the New Product's UUID in
	`vpn`, so resolve to its real vpn field; vendor-product rows carry "<part> (<vendor>)",
	so strip the trailing vendor suffix down to the part number Ascend expects."""

	if item.item_type == "New Product":
		return frappe.db.get_value("New Product", item.vpn, "vpn")
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
	with concurrent receiving edits. Called once the export sheets have built successfully."""

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)
	for item in doc.order_items:
		item.received = 1

	doc.flags.ignore_links = True
	doc.save()
	frappe.db.commit()


@frappe.whitelist()
def export_received_batch(docname):
	"""Build the two Ascend import sheets for a received order — a PO sheet from `order_items`
	and a Vendor Products sheet from `new_products` — bundle them into a single zip download,
	then mark the order's items as received."""

	doc = frappe.get_doc("Order Receipt", docname)

	po_sheet = build_import_sheet(
		_import_template_path("ascend_template_purchase_order.xlsx"),
		[_order_item_to_po_row(item) for item in doc.order_items],
	)
	products_sheet = build_import_sheet(
		_import_template_path("ascend_template_vendor_products.xlsx"),
		[to_import_row(product) for product in doc.new_products],
	)

	archive_buffer = io.BytesIO()
	with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
		archive.writestr(f"PO - {docname}.xlsx", po_sheet)
		archive.writestr(f"Products - {docname}.xlsx", products_sheet)

	# Only mark received once both sheets built, so a failure never silently receives the batch.
	_mark_items_received(docname)

	serve_file_download(f"{docname} - Ascend Import.zip", archive_buffer.getvalue(), "application/zip")