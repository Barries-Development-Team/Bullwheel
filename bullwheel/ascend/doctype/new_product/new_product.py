# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""New Product: a product (or a vendor's part number for an existing product) staged in
Bullwheel until it is imported into Ascend.

Bullwheel never writes to Ascend. A New Product lives in Bullwheel's own database, prints
labels and takes part in receiving, swap tagging and warehouse check-in as if it were a
product, and is exported on an Ascend Vendor Products import sheet. Once staff import that
sheet, `link_imported_product` (called by new_product_reconciliation) ties the record to the
Ascend Product Ascend created and moves Bullwheel's own records (prices, ski details) onto it.

Status lifecycle: Pending -> Exported -> Imported, with Import Failed (Ascend rejected the row)
and Cancelled as side exits.
"""

import frappe
from frappe.model import no_value_fields
from frappe.model.document import Document
from frappe.utils import now_datetime

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct
from bullwheel.ascend.doctype.vendor.vendor import Vendor
from bullwheel.ascend.doctype.vendor_product.vendor_product import generate_vpn, vendor_product_match_count

# Facts about Ascend's "Import from Excel" for Vendor Products (confirmed with Ascend, 2026-10):
#   * Ascend fills Products.ModifierLocationID, ConcurrencyToken and NonInventory itself, so the
#     sheet never has to supply them (IsNonInventory stays blank).
#   * The ID column is the record's database UUID, generated on insert: always left blank.
#   * The sheet has no Vendor column — the vendor is chosen in Ascend's import dialog — so every
#     sheet must hold one vendor's rows only.
#   * Imported VendorProducts.PartNumber equals the sheet's VPN, which is how an imported New
#     Product is matched back (vendor + VPN).
#   * A row whose UPC already belongs to an Ascend Product attaches the VPN to that product
#     instead of creating a duplicate (Existing Product entries). Expected, not yet confirmed
#     against a real import; the first Existing Product import should verify it.
#   * Categories.Topic is unique, so the category is exported by name.
# Maps Ascend Vendor Products template column headers to New Product fieldnames. Columns absent
# from this map (ID, IsNonInventory, eCommerce, Color Code, JH QTY) are left blank.
TEMPLATE_COLUMN_TO_FIELD = {
	"VPN": "vpn",
	"Category": "category",
	"Brand": "brand",
	"Description": "description",
	"Cost": "estimated_cost",
	"MSRP": "price",
	"UPC": "upc",
	"Color": "color",
	"Size": "size",
	"StyleNumber": "style_number",
	"StyleName": "style_name",
	"Year": "year",
	"Gender": "gender",
	"Season": "season",
	"MPN": "manufacturers_part_number",
	"CaseQty": "case_quantity",
	"CaseUPC": "case_upc",
	"CaseMSRP": "case_msrp",
}

CASE_COLUMNS = {"CaseQty", "CaseUPC", "CaseMSRP"}

# An Existing Product row only adds a vendor part number to a product Ascend (or an earlier
# import) already holds, so it carries just enough to identify the product and describe the
# vendor's part. Sending category/brand/etc. could overwrite the existing product's attributes.
EXISTING_PRODUCT_COLUMNS = {"VPN", "Description", "Cost", "UPC", "CaseQty", "CaseUPC", "CaseMSRP"}

# Fields an Existing Product copies from the product it refers to (an Ascend Product, or the
# pending New Product named in base_new_product).
EXISTING_PRODUCT_COPY_FIELDS = [
	"description", "upc", "brand", "style_name", "style_number", "size", "color",
	"gender", "season", "year", "category", "manufacturers_part_number", "price",
]

# New Product fieldnames copied onto a Ski with Bindings field of the same name. The Store SKU
# (the Ascend Product's name) fills `ski`, and `max_din` maps onto `din_range` separately.
SKI_WITH_BINDINGS_FIELDS = [
	"binding_brand_and_model", "radius", "tip_waist_tail",
	"condition", "top_condition", "base_condition",
]

# Product Price records to create when a New Product is matched, mapping each Product Price
# `pricing_type` to the New Product field holding the amount. A zero or empty amount is skipped.
PRODUCT_PRICE_TYPE_TO_FIELD = {
	"Ski Swap Price": "swap_price",
	"Online Listing Price": "online_price",
}

LOCKED_STATUSES = ("Exported", "Imported")

# Fields that may still change on a locked (Exported / Imported) record: the lifecycle itself,
# the link to the Ascend Product, and the prices (Swap Tag Batch re-prices them).
LOCK_EXEMPT_FIELDS = {
	"status", "exported_on", "imported_on", "export_batch", "ascend_product", "store_sku",
	"swap_price", "online_price",
}

# status_action -> (statuses it may start from, status it leads to)
STATUS_ACTIONS = {
	"mark_import_failed": (("Exported",), "Import Failed"),
	"requeue": (("Import Failed",), "Pending"),
	"revert_to_pending": (("Exported",), "Pending"),
	"cancel": (("Pending", "Import Failed"), "Cancelled"),
}


class NewProduct(Document):
	LABEL_RESOLUTION_FIELD = 'ascend_product'   # Once imported, labels print from the live Ascend Product (see label_printing/resolution.py).
	LABEL_RESOLUTION_OPTIONAL = True            # Until then there is nothing to hop to: the New Product prints itself.

	def before_insert(self):
		"""Generate this document's Vendor Part Number via Ascend's part-numbering scheme. Runs
		before insert (and before validate), so an Existing Product copies its source product's
		details first — the VPN is built from brand, model, size and color. A VPN supplied by
		the caller (the Existing Product dialog lets the user adjust the generated one) is kept."""
		if self.entry_type == "Existing Product":
			self._fill_from_existing_product()

		if self.vpn:
			return

		self.vpn = self._generate_vpn()

	def validate(self):
		"""Keep the record consistent while it waits for import: refuse edits once it is locked,
		fill an Existing Product from its source, re-render the Description and prices from
		their templates/rules, and reject identifiers Ascend or another pending New Product
		already holds (those belong on an Existing Product instead)."""
		self._ensure_unlocked()

		if self.upc and len(self.upc) > 20:
			frappe.throw('Max length for UPC is 20 characters.')

		if self.entry_type == "Existing Product":
			self._fill_from_existing_product()
		else:
			self._render_description()
			self._compute_pricing()

		self._validate_unique_identifiers()

		if self.is_new() and self.entry_type == "Existing Product":
			self._validate_vendor_does_not_carry_part_number()
		elif not self.is_new() and self.status == "Pending" and self.entry_type == "New Product":
			self._regenerate_vpn_if_inputs_changed()

	def on_trash(self):
		"""Refuse to delete a record Ascend may already know about, or one other Bullwheel
		records point at. Cancel it instead, which keeps the audit trail."""
		if self.status in LOCKED_STATUSES:
			frappe.throw(
				f"New Product {self.name} is {self.status} and cannot be deleted. "
				f"Revert it to Pending or Cancel it first.", frappe.LinkExistsError
			)
		references = self.referencing_documents()
		if references:
			frappe.throw(
				f"New Product {self.name} cannot be deleted because it is used by: "
				+ ", ".join(references) + ". Cancel it instead.", frappe.LinkExistsError
			)

	# ─── Identity and lifecycle ───────────────────────────────────────────────

	def referencing_documents(self) -> list[str]:
		"""Names of Bullwheel records that point at this New Product through a (doctype, name)
		reference: order items, warehouse bay rows and swap tag batch rows."""
		places = (
			("Order Receipt Item", "vpn", "item_type"),
			("Location Inventory", "product", "product_type"),
			("Swap Tag Batch Item", "product", "product_type"),
		)
		found = []
		for doctype, link_field, type_field in places:
			if not frappe.get_meta(doctype).has_field(type_field):
				continue
			count = frappe.db.count(doctype, {type_field: "New Product", link_field: self.name})
			if count:
				found.append(f"{count} {doctype} row(s)")
		return found

	def _ensure_unlocked(self):
		"""Reject edits to the identifying fields of an Exported/Imported record: the import
		sheet (or Ascend itself) already holds those values, so a silent edit would diverge
		from what Ascend received. Lifecycle fields and prices stay editable, and a status
		action (apply_status_action) bypasses the lock with flags.ignore_lock."""
		if self.is_new() or self.flags.ignore_lock:
			return

		before = self.get_doc_before_save()
		if not before or before.status not in LOCKED_STATUSES:
			return

		changed_labels = [
			field.label or field.fieldname
			for field in self.meta.fields
			if field.fieldtype not in no_value_fields
			and field.fieldname not in LOCK_EXEMPT_FIELDS
			and self.has_value_changed(field.fieldname)
		]
		if changed_labels:
			frappe.throw(
				f"New Product {self.name} is {before.status}, so {', '.join(changed_labels)} can no "
				f"longer be changed. Use Revert to Pending (Exported only) to edit it before re-exporting."
			)

	def _resolve_vendor_id(self):
		"""This document's Vendor's Ascend ID, needed by the VPN generator."""
		vendor_record = Vendor.get_values(self.vendor, ["id"])
		if not vendor_record:
			frappe.throw(f'Vendor "{self.vendor}" was not found in Ascend.')
		return vendor_record["id"]

	def _generate_vpn(self):
		"""Build a Vendor Part Number that no Ascend Vendor Product and no other pending New
		Product of this vendor uses."""
		return generate_vpn(
			vendor_id=self._resolve_vendor_id(),
			vpn_prefix=self.vpn_prefix,
			brand=self.brand,
			model=self.style_name,
			size=self.size,
			color=self.color,
			vendor=self.vendor,
			exclude_new_product=None if self.is_new() else self.name,
		)

	def _regenerate_vpn_if_inputs_changed(self):
		"""A pending record stays editable for days, so correcting its brand, model, size or
		color re-derives the VPN to match. Order items reference the record by name, not by VPN,
		so changing it does not orphan them."""
		if any(self.has_value_changed(field) for field in ("brand", "style_name", "size", "color", "vpn_prefix")):
			self.vpn = self._generate_vpn()

	def _validate_vendor_does_not_carry_part_number(self):
		"""An Existing Product exists because the vendor has no Vendor Product for it yet, so a
		VPN Ascend already holds for this vendor means this entry is not needed (or is a typo)."""
		if vendor_product_match_count(self._resolve_vendor_id(), self.vpn):
			frappe.throw(
				f'Ascend already has a Vendor Product "{self.vpn}" for {self.vendor}. '
				f'Add it to the order from the Vendor Product instead.'
			)

	def _validate_unique_identifiers(self):
		"""Block a UPC another record already holds. A UPC Ascend carries belongs to an existing
		product (use an Existing Product entry); a UPC another pending New Product carries is the
		same item (reuse that one). Only checked when the UPC is new or changed, so saving a
		long-pending record does not re-query Ascend every time."""
		if self.entry_type == "Existing Product" or not self.upc or not self.has_value_changed("upc"):
			return

		if AscendProduct._record_exists(self.upc):
			frappe.throw(
				f'UPC "{self.upc}" already exists in Ascend. Add a vendor part number to the '
				f'existing product with an Existing Product entry instead.'
			)

		other = frappe.db.get_value(
			"New Product",
			{"upc": self.upc, "status": ["!=", "Cancelled"], "name": ["!=", self.name or ""]},
			"name",
		)
		if other:
			frappe.throw(
				f'UPC "{self.upc}" is already on pending New Product {other}. Use an Existing '
				f'Product entry referring to it instead.'
			)

	# ─── Content ──────────────────────────────────────────────────────────────

	def _fill_from_existing_product(self):
		"""Copy the product details of an Existing Product entry from its source: the Ascend
		Product it links to, or — when the product is not in Ascend yet — the pending New Product
		named in base_new_product. Requires a UPC on the source, because Ascend attaches an
		imported VPN to an existing product by UPC. Once the base New Product has been matched to
		Ascend, this entry adopts that Ascend Product."""
		if self.ascend_product:
			source = AscendProduct.get_values(self.ascend_product, EXISTING_PRODUCT_COPY_FIELDS)
			if not source:
				frappe.throw(f'Ascend Product "{self.ascend_product}" was not found.')
			self.store_sku = self.ascend_product
		elif self.base_new_product:
			source = frappe.db.get_value(
				"New Product", self.base_new_product,
				EXISTING_PRODUCT_COPY_FIELDS + ["status", "ascend_product"], as_dict=True,
			)
			if not source or source.status == "Cancelled":
				frappe.throw(f'Pending New Product "{self.base_new_product}" is missing or cancelled.')
			if source.ascend_product:
				self.ascend_product = source.ascend_product
				self.store_sku = source.ascend_product
		else:
			frappe.throw("An Existing Product entry needs an Ascend Product or a Pending New Product.")

		for field in EXISTING_PRODUCT_COPY_FIELDS:
			self.set(field, source.get(field))

		if not self.upc:
			frappe.throw(
				"The existing product has no UPC, so Ascend cannot attach a new vendor part "
				"number to it from an import sheet. Add the Vendor Product in Ascend directly."
			)

	def _compute_pricing(self):
		"""Re-derive Swap Price and Online Price from the selected Product Pricing Rule and this
		document's MSRP (the `price` field), but only when the MSRP or the rule changed, so a
		price adjusted afterwards (Swap Tag Batch) is not overwritten by an unrelated save. Runs
		server-side — and on the Quick Entry receiving path, where the form's live-preview script
		(see new_product.js) never executes. With no rule selected the prices are left as
		entered, matching the form's manual-entry path."""
		if not self.product_pricing_rule:
			return
		if not (self.is_new() or self.has_value_changed("price") or self.has_value_changed("product_pricing_rule")):
			return

		computed_prices = compute_swap_and_online_price(self.price, self.product_pricing_rule)
		self.swap_price = computed_prices["swap_price"]
		self.online_price = computed_prices["online_price"]

	def _render_description(self):
		"""Re-render the Description from the chosen Description Template (if any) so the saved
		value always reflects the template's current definition and this document's current
		field values, rather than trusting whatever the client last previewed. Runs server-side
		— so it also works in the Quick Entry receiving modal, where the form's live-preview
		script (see new_product.js) never executes."""
		if self.description_template:
			template = frappe.get_cached_doc("Description Template", self.description_template)
			self.description = template.render(self)

	# ─── Matching an imported product ─────────────────────────────────────────

	def link_imported_product(self, ascend_product_name: str):
		"""Tie this record to the Ascend Product Ascend created from it and mark it Imported.
		Bullwheel's own records for the product are created now that a real Ascend Product exists
		to link to: a Product Price per swap/online amount and, for a ski, its Ski with Bindings.
		Existing Product entries only gain the link — their prices and ski details already
		belong to the product. Safe to call twice."""
		self.flags.ignore_lock = True
		self.ascend_product = ascend_product_name
		self.store_sku = ascend_product_name
		self.status = "Imported"
		self.imported_on = now_datetime()
		self.save()

		if self.entry_type == "Existing Product":
			return

		self._create_product_prices()
		if self._is_ski_hardgood():
			self._create_ski_with_bindings()

	def _is_ski_hardgood(self):
		"""True when this product's category marks it as a ski that needs a Ski with Bindings
		record. The matching prefix is configured on Bullwheel Settings so the receiving rule
		can change without a code deploy."""
		prefix = frappe.db.get_single_value("Bullwheel Settings", "ski_category_prefix")
		return bool(prefix) and prefix in (self.category or "")

	def _create_ski_with_bindings(self):
		"""Create the Ski with Bindings record for a received ski, linking it to the Ascend
		Product (named by store_sku) and copying the ski-detail fields entered on the receiving
		form. New Product's `max_din` maps onto the doctype's `din_range` field."""
		if frappe.db.exists("Ski with Bindings", {"ski": self.store_sku}):
			return

		frappe.get_doc({
			"doctype": "Ski with Bindings",
			"ski": self.store_sku,
			"din_range": self.max_din,
			**{field: self.get(field) for field in SKI_WITH_BINDINGS_FIELDS},
		}).insert()

	def _create_product_prices(self):
		"""Create a Product Price record for each Swap and Online price, linking it to the Ascend
		Product (named by store_sku). A price of 0 or None is skipped, and a price that already
		exists is left alone. Product Price names itself via its own autoname."""
		for pricing_type, field in PRODUCT_PRICE_TYPE_TO_FIELD.items():
			price = self.get(field)
			if not price:
				continue

			price_kind = "SWAP" if pricing_type == "Ski Swap Price" else "ONLINE"
			if frappe.db.exists("Product Price", f"PRICE-{price_kind}-{self.store_sku}"):
				continue

			frappe.get_doc({
				"doctype": "Product Price",
				"pricing_type": pricing_type,
				"product": self.store_sku,
				"price": price,
			}).insert()


@frappe.whitelist()
def apply_status_action(name: str, action: str):
	"""Move a New Product along its lifecycle: mark an export as failed, re-queue it, revert an
	export so it can be edited, or cancel it. Each action is only valid from certain statuses
	(see STATUS_ACTIONS); Imported records are final."""
	if action not in STATUS_ACTIONS:
		frappe.throw(f'Unknown action "{action}".')

	allowed_from, new_status = STATUS_ACTIONS[action]
	document = frappe.get_doc("New Product", name)
	document.check_permission("write")
	if document.status not in allowed_from:
		frappe.throw(f'New Product {name} is {document.status}; "{action}" needs it to be {" or ".join(allowed_from)}.')

	document.flags.ignore_lock = True
	document.status = new_status
	if new_status == "Pending":
		document.exported_on = None
		document.export_batch = None
	document.save()
	return document.status


def export_blocker(new_product_name: str) -> str | None:
	"""Why a New Product cannot go on an import sheet right now, or None when it can. Held back:
	a record that no longer exists or was cancelled, and an Existing Product entry whose base New
	Product has not been imported and matched yet — Ascend would create a duplicate product
	instead of attaching the part number to it."""
	product = frappe.db.get_value(
		"New Product", new_product_name, ["status", "entry_type", "base_new_product", "ascend_product"], as_dict=True
	)
	if not product:
		return f"New Product {new_product_name} no longer exists"
	if product.status == "Cancelled":
		return f"New Product {new_product_name} was cancelled"
	if product.entry_type == "Existing Product" and product.base_new_product and not product.ascend_product:
		base = frappe.db.get_value("New Product", product.base_new_product, ["status", "ascend_product"], as_dict=True)
		if not base or not base.ascend_product:
			return f"it refers to pending New Product {product.base_new_product}, which is not imported into Ascend yet"
	return None


def mark_exported(new_product_name: str, export_batch: str | None = None) -> None:
	"""Move a New Product to Exported and stamp when (and, for a Bulk Product Import, in which
	batch) it was exported. Bypasses the edit lock — exporting is what creates it."""
	document = frappe.get_doc("New Product", new_product_name)
	document.flags.ignore_lock = True
	document.status = "Exported"
	document.exported_on = now_datetime()
	if export_batch:
		document.export_batch = export_batch
	document.save()


@frappe.whitelist()
def generate_description(template_name, product):
	"""Whitelisted endpoint the New Product form calls on every relevant field change to
	preview the rendered Description before save. `product` carries the in-progress form
	values (not yet saved), so the template renders against exactly what the user currently
	sees rather than the last-saved document."""
	if isinstance(product, str):
		product = frappe.parse_json(product)

	template = frappe.get_cached_doc("Description Template", template_name)
	return template.render(frappe._dict(product))


def to_import_row(product):
	"""Project one New Product onto the Ascend Vendor Products template column headers,
	returning a {template_column: value} dict. The case columns are dropped when the row
	carries no case, and an Existing Product row is cut down to the columns that identify the
	product and describe the vendor's part (see EXISTING_PRODUCT_COLUMNS). Duck-typed on
	`product` (reads attributes by fieldname), so it works on a document or a plain record."""
	existing = getattr(product, "entry_type", None) == "Existing Product"
	row = {}
	for template_column, field_name in TEMPLATE_COLUMN_TO_FIELD.items():
		if existing and template_column not in EXISTING_PRODUCT_COLUMNS:
			continue
		if template_column in CASE_COLUMNS and not product.case:
			continue
		row[template_column] = getattr(product, field_name, None)
	return row


@frappe.whitelist()
def compute_swap_and_online_price(msrp: float, product_pricing_rule_name: str) -> dict:
	computed_prices = {
		'swap_price': 0.0,
		'online_price': 0.0
	}
	if not msrp:
		return computed_prices

	product_pricing_rule = frappe.get_cached_doc('Product Pricing Rule', product_pricing_rule_name)

	computed_prices["swap_price"] = swap_price if (swap_price := round(msrp * (1 - product_pricing_rule.swap_percentage)) - 0.05) > 0 else 0
	computed_prices["online_price"] = online_price if (online_price := round(msrp * (1 - product_pricing_rule.online_percentage)) - 0.05) > 0 else 0

	return computed_prices
