# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.ascend.doctype.vendor_product.vendor_product import VendorProduct


class OrderReceiptItem(Document):
	# description/upc are computed from the linked Vendor Product on every load, through a
	# short-TTL Redis cache (VendorProduct.get_bulk_short_cached_values) rather than a live Ascend
	# query per row — OrderReceipt.onload() batch-warms this cache for every row's vpn in one
	# query before any row is serialized. See order_receipt.py's OrderReceipt.onload.

	LABEL_RESOLUTION_FIELD = 'vpn'  # Dynamic Link (on item_type) -> Vendor Product or New Product; label prints resolve through it (see label_printing/resolution.py)

	def _ascend_fields(self):
		"""Fetch and memoize the linked product's description/upc for this document instance.
		A Vendor Product is read through VendorProduct's short-TTL cache rather than a live
		query; a New Product (not in Ascend yet) is read from Bullwheel's own database. Returns
		None when no vpn is set or the linked record doesn't resolve."""
		if not hasattr(self, "_ascend_field_cache"):
			if not self.vpn:
				self._ascend_field_cache = None
			elif self.item_type == "New Product":
				self._ascend_field_cache = frappe.db.get_value(
					"New Product", self.vpn, ["description", "upc"], as_dict=True
				)
			else:
				self._ascend_field_cache = (
					VendorProduct.get_bulk_short_cached_values([self.vpn], ["description", "upc"]).get(self.vpn)
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
