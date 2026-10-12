# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import io
import json
import re
import zipfile

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core import get_default_ascend_database
from bullwheel.ascend.doctype.vendor_product.vendor_product import VendorProduct
from bullwheel.ascend.doctype.new_product.new_product import export_blocker, mark_exported, to_import_row
from bullwheel.ascend.doctype.vendor.vendor import Vendor
from bullwheel.ascend.import_sheets import build_import_sheet, serve_file_download


class OrderReceipt(Document):

	def onload(self):
		"""Batch-warm the short-TTL Vendor Product cache for every order item's vpn in one Ascend
		query, before Frappe serializes the child rows (each row's description/upc is_virtual
		property reads this same cache — see order_receipt_item.py). Runs once per client-side
		form load/reload (frappe.desk.form.load.getdoc calls onload before appending the doc to
		the response), which is also what fires after update_table/add_or_increment_item's
		enqueued jobs: their doc.save() publishes a doc_update realtime event, and the client's
		non-dirty-form listener reload_doc()'s the form, which round-trips through getdoc again."""
		vpns = [item.vpn for item in self.order_items if item.vpn and item.item_type != "New Product"]
		if vpns:
			VendorProduct.get_bulk_short_cached_values(vpns, ["description", "upc"])

	def validate(self):
		"""Confirm the seeded vendor resolves in Ascend, warming Vendor.get_cached_value's cache
		for the receiving flow's later scan_item/stage_existing_product lookups, and refuse to
		complete receiving while a New Product on the order has not been exported yet — its
		import sheet would never reach Ascend."""
		_resolve_vendor_id(self.vendor)

		if self.order_status == "Received" and self.has_value_changed("order_status"):
			unexported = _unexported_new_products(self)
			if unexported:
				frappe.throw(
					"Export the received batch before completing receiving. These New Products have "
					"not been exported to an import sheet yet: " + ", ".join(unexported)
				)

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

# New Product statuses that can still be matched on a scan: the product is staged in Bullwheel
# (or exported and awaiting import). Imported products are in Ascend, so Ascend finds them.
STAGED_NEW_PRODUCT_STATUSES = ["Pending", "Exported", "Import Failed"]


def _unexported_new_products(doc) -> list[str]:
	"""Names of New Products on this order that are still Pending (not on any export yet)."""
	names = {item.vpn for item in doc.order_items if item.item_type == "New Product" and item.vpn}
	if not names:
		return []
	return frappe.get_all(
		"New Product", filters={"name": ["in", list(names)], "status": ["in", ["Pending", "Import Failed"]]}, pluck="name"
	)


def _resolve_vendor_id(vendor):
	"""Look up a Vendor's Ascend ID through Vendor.get_cached_value, throwing if the vendor
	doesn't resolve in Ascend. Shared by validate, scan_item, get_vendor_id, and
	stage_existing_product — every place this receipt needs the vendor's Ascend id."""
	vendor_id = Vendor.get_cached_value(name=vendor, field='id')
	if not vendor_id:
		frappe.throw(f'Vendor "{vendor}" was not found in Ascend.')
	return vendor_id

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

def add_or_increment_item(docname, vpn, cost=None, item_type="Vendor Product"):
	"""Add an order item for the given Vendor Product (or New Product, when item_type says so), or
	bump its quantity if an unreceived row for the same item already exists. Rows already marked received are treated as read-only
	history from a prior batch and are never matched, so a new row is appended instead. Used
	by the scan flow; runs under the row lock so concurrent scans serialize instead of racing.
	description/upc are computed (is_virtual, see order_receipt_item.py), not passed in — see
	OrderReceipt.onload for how they get warmed for display."""

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)

	existing = next(
		(row for row in doc.order_items if row.vpn == vpn and row.item_type == item_type and not row.received), None
	)
	if existing:
		existing.quantity += 1
	else:
		doc.append("order_items", {
			"item_type": item_type,
			"vpn": vpn,
			"quantity": 1,
			"cost": cost,
		})

	doc.flags.ignore_links = True
	doc.save()
	frappe.db.commit()

@frappe.whitelist()
def queue_add_or_increment_item(docname, vpn, cost=None, item_type="Vendor Product"):
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
		item_type=item_type,
	)

def _find_staged_new_product(identifier: str, vendor: str | None = None):
	"""Find a New Product still staged in Bullwheel that matches a scanned identifier (UPC, VPN,
	manufacturer part number or case UPC). With `vendor`, only that vendor's products are
	searched; with `vendor=None` every vendor's are, which finds a product pending on another
	vendor's order. Returns the first match or None."""
	filters = {"status": ["in", STAGED_NEW_PRODUCT_STATUSES]}
	if vendor:
		filters["vendor"] = vendor
	matches = frappe.get_all(
		"New Product",
		filters=filters,
		or_filters=[
			["upc", "=", identifier], ["vpn", "=", identifier],
			["manufacturers_part_number", "=", identifier], ["case_upc", "=", identifier],
		],
		fields=[
			"name", "vpn", "description", "upc", "brand", "style_name", "size", "color",
			"estimated_cost as cost", "vendor",
		],
		order_by="creation asc",
		limit=1,
	)
	return matches[0] if matches else None


@frappe.whitelist()
def scan_item(id: str, vendor: str):
	"""Resolve a scanned identifier to an item this order can receive. Checks, in order: a New
	Product already staged for this vendor, a Vendor Product in Ascend for this vendor, any
	Product in Ascend, then a New Product staged for another vendor. Returns a (status, record)
	tuple; status is one of 'new product found', 'vpn found', 'product found',
	'pending product found' or 'not found'."""

	vendor_id = _resolve_vendor_id(vendor)

	# A product this vendor already has staged in Bullwheel: scanning its second unit must add to
	# the same New Product rather than start another.
	if staged := _find_staged_new_product(id, vendor):
		return ('new product found', staged)

	# Determine if Vendor Product exists for the scanned item.

	vpn_query = ('SELECT VP.PartNumber as vpn, VP.Cost as cost, P.Description as description, P.UPC as upc  '
			'FROM VendorProducts as VP '
			'JOIN Products as P ON VP.ProductID = P.ID '
			'WHERE VP.VendorID = %s AND (P.UPC = %s OR P.[Store UPC] = %s OR P.MfgrPartNo = %s)'
	)

	values = [vendor_id, id, id, id]

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

	# Not in Ascend: it may still be staged as another vendor's New Product, in which case this
	# vendor needs a vendor part number for that product rather than a second product record.
	if pending := _find_staged_new_product(id):
		return ('pending product found', pending)

	return ('not found', None)


@frappe.whitelist()
def get_vendor_id(vendor: str) -> str:
	"""Resolve a Vendor's Ascend ID through Vendor.get_cached_value, for client-side flows (the
	vendor-link dialog's VPN generation) that need it without a full Order Receipt round trip."""
	return _resolve_vendor_id(vendor)


@frappe.whitelist()
def stage_existing_product(docname, part_number, cost, ascend_product=None, base_new_product=None):
	"""Stage a vendor part number for a product this receipt's vendor does not carry yet: create an
	Existing Product New Product referring to the Ascend Product (or to the New Product still
	pending import), then add or increment the matching order item. Bullwheel cannot write the
	Vendor Product into Ascend, so the entry waits in Bullwheel until it is exported on a Vendor
	Products import sheet. Runs synchronously (not enqueued) so a rejected entry — no UPC to attach
	the part number by, a VPN the vendor already has — surfaces directly in the caller's dialog."""

	if bool(ascend_product) == bool(base_new_product):
		frappe.throw("Choose either an Ascend Product or a pending New Product.")

	vendor, vpn_prefix = frappe.db.get_value("Order Receipt", docname, ["vendor", "vpn_prefix"])
	if not vendor:
		frappe.throw(f'Order Receipt "{docname}" has no vendor set.')

	new_product = frappe.get_doc({
		"doctype": "New Product",
		"entry_type": "Existing Product",
		"vendor": vendor,
		"vpn_prefix": vpn_prefix,
		"vpn": part_number,
		"estimated_cost": flt(cost),
		"ascend_product": ascend_product,
		"base_new_product": base_new_product,
	}).insert()

	add_or_increment_item(docname, new_product.name, cost=cost, item_type="New Product")
	return new_product.name


def _import_template_path(filename):
	"""Absolute path to an Ascend import template shipped with the app."""
	return frappe.get_app_path("bullwheel", "ascend", "import_templates", filename)


# A vendor display name is the final parenthesized group, preceded by whitespace:
# "<part number> (<vendor>)". Anchored to end-of-string so any parentheses inside the
# part number itself are left untouched.
_VENDOR_SUFFIX_PATTERN = re.compile(r"\s+\([^()]*\)$")


def _resolve_ascend_vpn(item):
	"""The bare Ascend VPN for a PO line. A Vendor Product order item's `vpn` carries the Vendor
	Product's docname, "<part> (<vendor>)", so strip the trailing vendor suffix down to the part
	number Ascend expects. A New Product item's `vpn` is the New Product's name; its part number
	is the New Product's own VPN."""

	if item.item_type == "New Product":
		return frappe.db.get_value("New Product", item.vpn, "vpn")
	return _VENDOR_SUFFIX_PATTERN.sub("", item.vpn)


def _single_line(value):
	"""Collapse a value onto a single line, joining what was split across lines with a space.
	A newline inside a spreadsheet cell is a literal line break in the imported value, which
	Ascend's importer does not expect on a purchase order line; collapsing keeps the whole
	note without the embedded break. Also strips the leading/trailing and repeated whitespace
	that hand-entered comments tend to carry."""

	if not value:
		return value

	return " ".join(str(value).split())


def _export_cost(item):
	"""An order item's cost rounded to the item's own Currency precision. The raw field value
	can carry full binary float precision — costs derived from a buyout allocation come back
	with 16 decimal places — and the exporter writes whatever it is given straight into the
	sheet. Ascend's Cost column is money (4 decimal places), so an unrounded cost is rounded
	somewhere inside Ascend instead, and every extended total Ascend derives from it inherits
	the artifact. Rounding here means the sheet carries exactly the cost the receipt shows."""

	return flt(item.cost, item.precision("cost") or 2)


def _order_item_to_po_row(item):
	"""Project one order item onto the Ascend Vendor Order (PO) template column headers."""

	return {
		"Identifier": _resolve_ascend_vpn(item),
		"Description": _single_line(item.description),
		"Qty": item.quantity,
		"Cost": _export_cost(item),
		"Comments": _single_line(item.comments),
	}


def _unexportable_reason(item):
	"""Why an order item cannot go on this export, or None when it can (see
	new_product.export_blocker). Vendor Product lines are always exportable."""

	if item.item_type != "New Product":
		return None
	return export_blocker(item.vpn)


def _build_export_files(doc, items, statuses=("Pending",)):
	"""Build the Ascend import sheets for these order items: the PO sheet, plus a Vendor Products
	sheet holding the New Products among them whose status is in `statuses` (only the Pending ones
	for a normal export, so a re-export never duplicates an imported product; every unfinished one
	for a re-download). Returns (po_sheet_bytes, products_sheet_bytes_or_None,
	included_new_product_names)."""

	po_sheet = build_import_sheet(
		_import_template_path("ascend_template_purchase_order.xlsx"),
		[_order_item_to_po_row(item) for item in items],
	)

	new_product_names = list(dict.fromkeys(
		item.vpn for item in items if item.item_type == "New Product"
	))
	pending_names = frappe.get_all(
		"New Product", filters={"name": ["in", new_product_names], "status": ["in", list(statuses)]}, pluck="name",
		order_by="creation asc",
	) if new_product_names else []

	products_sheet = None
	if pending_names:
		products_sheet = build_import_sheet(
			_import_template_path("ascend_template_vendor_products.xlsx"),
			[to_import_row(frappe.get_doc("New Product", name)) for name in pending_names],
		)
	return po_sheet, products_sheet, pending_names


def _mark_exported(docname, row_names, new_product_names):
	"""Flag the exported order items as received and their Pending New Products as Exported, inside
	a row lock so it serializes with concurrent receiving edits. Called once the export files have
	built successfully."""

	lock_row(docname)

	doc = frappe.get_doc("Order Receipt", docname)
	for item in doc.order_items:
		if item.name in row_names:
			item.received = 1

	doc.flags.ignore_links = True
	doc.save()

	for name in new_product_names:
		mark_exported(name)

	frappe.db.commit()


@frappe.whitelist()
def export_received_batch(docname, redownload=0):
	"""Build the Ascend import files for an order and serve them: the PO sheet for the unreceived
	order items, plus a Vendor Products sheet for the New Products among them (zipped together
	when both exist). Marks the items received and the New Products Exported. Lines whose New
	Product cannot be imported yet are left unreceived and listed in the download. With
	redownload=1, every order item is exported again and nothing is marked — for a download that
	failed in the browser."""

	redownload = cint(redownload)
	doc = frappe.get_doc("Order Receipt", docname)

	candidates = [item for item in doc.order_items if redownload or not item.received]
	exportable, held_back = [], []
	for item in candidates:
		reason = _unexportable_reason(item)
		if reason:
			held_back.append(f"{item.vpn}: {reason}")
		else:
			exportable.append(item)

	if not exportable:
		frappe.throw("There is nothing to export." + (" " + "; ".join(held_back) if held_back else ""))

	po_sheet, products_sheet, included_names = _build_export_files(
		doc, exportable, STAGED_NEW_PRODUCT_STATUSES if redownload else ("Pending",)
	)

	# Only mark received once the sheets have built, so a failure never silently receives the batch.
	if not redownload:
		_mark_exported(docname, {item.name for item in exportable}, included_names)

	spreadsheet_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
	if not products_sheet and not held_back:
		serve_file_download(f"PO - {docname}.xlsx", po_sheet, spreadsheet_type)
		return

	archive = io.BytesIO()
	with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
		if products_sheet:
			bundle.writestr(f"1 - Vendor Products - {docname}.xlsx", products_sheet)
		bundle.writestr(f"2 - PO - {docname}.xlsx", po_sheet)
		if held_back:
			bundle.writestr(
				"NOT EXPORTED.txt",
				"These order lines were left unreceived because Ascend cannot import them yet:\n\n"
				+ "\n".join(held_back) + "\n",
			)
	serve_file_download(f"Receiving export - {docname}.zip", archive.getvalue(), "application/zip")
