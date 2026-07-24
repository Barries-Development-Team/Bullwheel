# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import random

import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.ascend_product.ascend_product import AscendProduct
from bullwheel.ascend.doctype.vendor.vendor import Vendor
from bullwheel.ascend.doctype.vendor_product.vendor_product import create_vendor_product, generate_vpn

# Maps Ascend Vendor Products template column headers to New Product fieldnames.
# Columns absent from this map (ID, IsNonInventory, eCommerce, Color Code, JH QTY)
# are left blank because they have no equivalent field in the New Product DocType.
TEMPLATE_COLUMN_TO_FIELD = {
	"VPN": "vpn",
	"Category": "category",
	"Brand": "brand",
	"Description": "description",
	"Cost": "cost",
	"MSRP": "msrp",
	"UPC": "upc",
	"Color": "color",
	"Size": "size",
	"StyleNumber": "style_number",
	"StyleName": "style_name",
	"Year": "year",
	"Gender": "gender",
	"Season": "season",
	"MPN": "mpn",
	"CaseQty": "case_quantity",
	"CaseUPC": "case_upc",
	"CaseMSRP": "cast_msrp",
}

CASE_COLUMNS = {"CaseQty", "CaseUPC", "CaseMSRP"}

# New Product fieldnames that map onto an Ascend Product field of the same name.
ASCEND_PRODUCT_FIELDS = [
	"description", "price", "estimated_cost", "upc", "manufacturers_part_number",
	"brand", "color", "size", "style_name", "style_number", "season", "year", "gender",
]

# New Product fieldnames copied onto a Ski with Bindings field of the same name. The Store SKU
# (the Ascend Product's name) fills `ski`, and `max_din` maps onto `din_range` separately.
SKI_WITH_BINDINGS_FIELDS = [
	"binding_brand_and_model", "radius", "tip_waist_tail",
	"condition", "top_condition", "base_condition",
]

STORE_SKU_RANDOM_DIGITS = 8
MAX_STORE_SKU_ATTEMPTS = 20

# Product Price records to create in after_insert, mapping each Product Price `pricing_type`
# to the New Product field holding the computed amount. A zero or empty amount is skipped.
PRODUCT_PRICE_TYPE_TO_FIELD = {
	"Ski Swap Price": "swap_price",
	"Online Listing Price": "online_price",
}


def _generate_store_sku(description):
	"""Build a new Ascend Store SKU: the first 3 letters of `description`, then
	STORE_SKU_RANDOM_DIGITS random digits, then its last letter, all upper-cased. Retries
	against Ascend on collision — the random digits make one vanishingly unlikely, but a fresh
	Products table lookup backs every attempt rather than trusting a single draw to be unique."""
	prefix = description[:3].upper()
	suffix = description[-1:].upper()

	for _ in range(MAX_STORE_SKU_ATTEMPTS):
		digits = "".join(str(random.randint(0, 9)) for _ in range(STORE_SKU_RANDOM_DIGITS))
		candidate = f"{prefix}{digits}{suffix}"
		if not AscendProduct._record_exists(candidate):
			return candidate

	frappe.throw(f"Could not generate a unique Store SKU after {MAX_STORE_SKU_ATTEMPTS} attempts.")


class NewProduct(Document):
	def autoname(self):
		"""Generate the Store SKU up front. It doubles as this document's own name (the
		"field:store_sku" autoname rule picks up whatever this sets) and as the Ascend
		Product's primary key created in after_insert, so it must exist before either naming
		step runs. The Description is rendered first because the Store SKU is derived from it."""
		self._render_description()
		if not self.store_sku:
			self.store_sku = _generate_store_sku(self.description)

	def before_insert(self):
		"""Generate this document's Vendor Part Number via Ascend's part-numbering scheme,
		when a vendor was seeded onto this document (see Order Receipt's
		open_new_product_form_dialog). Must run before insert: after_insert's
		create_vendor_product call passes self.vpn on as the new Vendor Product's part
		number. Products created without a vendor context (e.g. from the New Product list
		view) are left with no VPN, same as before this existed."""
		if not self.vendor:
			return

		self.vpn = generate_vpn(
			vendor_id=self._resolve_vendor_id(),
			vpn_prefix=self.vpn_prefix,
			brand=self.brand,
			model=self.style_name,
			size=self.size,
			color=self.color,
		)

	def validate(self):
		"""Re-render the Description (in case fields changed since autoname) and re-derive the
		Swap and Online prices, so both hold on the Quick Entry receiving path (which does not
		run the form's field scripts)."""
		self._render_description()
		self._compute_pricing()

	def _compute_pricing(self):
		"""Re-derive Swap Price and Online Price from the selected Product Pricing Rule and this
		document's MSRP (the `price` field), so the saved values always reflect the rule's current
		percentages and this document's current MSRP rather than trusting whatever the client last
		previewed. Runs server-side — and on the Quick Entry receiving path, where the form's
		live-preview script (see new_product.js) never executes. With no rule selected the prices
		are left as entered, matching the form's manual-entry path."""
		if not self.product_pricing_rule:
			return

		computed_prices = compute_swap_and_online_price(self.price, self.product_pricing_rule)
		self.swap_price = computed_prices["swap_price"]
		self.online_price = computed_prices["online_price"]


	def _render_description(self):
		"""Re-render the Description from the chosen Description Template (if any) so the saved
		value always reflects the template's current definition and this document's current
		field values, rather than trusting whatever the client last previewed. Runs server-side
		— and before autoname, which builds the Store SKU from the Description — so it also
		works in the Quick Entry receiving modal, where the form's live-preview script (see
		new_product.js) never executes."""
		if self.description_template:
			template = frappe.get_cached_doc("Description Template", self.description_template)
			self.description = template.render(self)

	def after_insert(self):
		"""Create the Ascend Product this New Product represents, then a Ski with Bindings
		record when the category marks it as a ski, and — when a vendor was seeded onto this
		document (see Order Receipt's open_new_product_form_dialog) — the Vendor Product
		linking it to that vendor. Runs after the local New Product record is committed, so a
		Store SKU collision or Ascend connectivity failure surfaces as an ordinary insert error
		rather than leaving Ascend and Bullwheel out of sync."""
		ascend_product = frappe.get_doc({
			"doctype": "Ascend Product",
			"store_sku": self.store_sku,
			**{field: self.get(field) for field in ASCEND_PRODUCT_FIELDS},
		})
		ascend_product.insert()

		if self._is_ski_hardgood():
			self._create_ski_with_bindings()

		self._create_product_prices()

		if self.vendor:
			product_record = AscendProduct.get_values(self.store_sku, ["id"])
			create_vendor_product(
				vendor_id=self._resolve_vendor_id(),
				product_id=product_record["id"],
				part_number=self.vpn,
				cost=self.estimated_cost,
				description=self.description,
				case_quantity=self.case_quantity if self.case else None,
				case_upc=self.case_upc if self.case else None,
				case_msrp=self.case_msrp if self.case else None,
			)

	def _resolve_vendor_id(self):
		"""Look up this document's seeded Vendor's Ascend ID. Shared by before_insert (VPN
		generation) and after_insert (Vendor Product creation) — both need the same lookup
		once a vendor has been seeded onto the document."""
		vendor_record = Vendor.get_values(self.vendor, ["id"])
		if not vendor_record:
			frappe.throw(f'Vendor "{self.vendor}" was not found in Ascend.')
		return vendor_record["id"]

	def _is_ski_hardgood(self):
		"""True when this product's category marks it as a ski that needs a Ski with Bindings
		record. The matching prefix is configured on Bullwheel Settings so the receiving rule
		can change without a code deploy."""
		prefix = frappe.db.get_single_value("Bullwheel Settings", "ski_category_prefix")
		return bool(prefix) and prefix in (self.category or "")

	def _create_ski_with_bindings(self):
		"""Create the Ski with Bindings record for a received ski, linking it to the Ascend
		Product just created (named by store_sku) and copying the ski-detail fields entered on
		the receiving form. New Product's `max_din` maps onto the doctype's `din_range` field."""
		ski = frappe.get_doc({
			"doctype": "Ski with Bindings",
			"ski": self.store_sku,
			"din_range": self.max_din,
			**{field: self.get(field) for field in SKI_WITH_BINDINGS_FIELDS},
		})
		ski.insert()

	def _create_product_prices(self):
		"""Create a Product Price record for each computed Swap and Online price, linking it to the
		Ascend Product just created (named by store_sku). A price of 0 or None is skipped, so a
		product priced only for one channel — or one with no pricing rule at all — gets only the
		records it has amounts for. Product Price names itself via its own autoname."""
		for pricing_type, field in PRODUCT_PRICE_TYPE_TO_FIELD.items():
			price = self.get(field)
			if not price:
				continue

			frappe.get_doc({
				"doctype": "Product Price",
				"pricing_type": pricing_type,
				"product": self.store_sku,
				"price": price,
			}).insert()


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
	"""Project one New Product row onto the Ascend Vendor Products template column headers,
	returning a {template_column: value} dict. The case columns are dropped when the row
	carries no case. Duck-typed on `product` (reads attributes by fieldname), so it serves
	both Order Receipt's `new_products` rows and Bulk Product Import's `table_frll` rows."""
	row = {}
	for template_column, field_name in TEMPLATE_COLUMN_TO_FIELD.items():
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