# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from bullwheel.ascend.doctype.vendor_product.vendor_product import VendorProduct


class OrderReceiptItem(Document):
	# description/upc are computed from the linked Vendor Product on every load, through a
	# short-TTL Redis cache (VendorProduct.get_bulk_short_cached_values) rather than a live Ascend
	# query per row — OrderReceipt.onload() batch-warms this cache for every row's vpn in one
	# query before any row is serialized. See order_receipt.py's OrderReceipt.onload.

	LABEL_RESOLUTION_FIELD = 'vpn'  # Link -> Vendor Product; label prints resolve through it (see label_printing/resolution.py)

	def _ascend_fields(self):
		"""Fetch and memoize the linked Vendor Product's mirrored description/upc fields for this
		document instance, sourced through VendorProduct's short-TTL cache rather than a live
		query. Returns None when no vpn is set or the linked Vendor Product doesn't resolve in
		Ascend (e.g. mid-creation during the vendor-link/new-product flow)."""
		if not hasattr(self, "_ascend_field_cache"):
			self._ascend_field_cache = (
				VendorProduct.get_bulk_short_cached_values([self.vpn], ["description", "upc"]).get(self.vpn)
				if self.vpn else None
			)
		return self._ascend_field_cache

	@property
	def description(self):
		fields = self._ascend_fields()
		return fields.get("description") if fields else None

	@property
	def upc(self):
		fields = self._ascend_fields()
		return fields.get("upc") if fields else None
