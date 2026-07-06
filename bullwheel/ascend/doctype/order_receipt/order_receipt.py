# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database
from bullwheel.ascend.doctype.vendor.vendor import Vendor


class OrderReceipt(Document):

	def get_vendor_id(self):
		"""Get the Ascend Vendor ID for the vendor associated with this order receipt."""

		if self.vendor:
			vendor_id = Vendor.get_values(self.vendor, ["id"]).id
			return vendor_id
		else:
			raise ValueError("Vendor is not set for this order receipt.")
	
	@frappe.whitelist()
	def scan_item(self, id: str):
		"""Determine existance of a Vendor Product for the scanned item, and return the Vendor Product's VPN if it exists."""

		vendor_id = self.get_vendor_id()

		# Determine if Vendor Product exists for the scanned item.

		vpn_query = ('SELECT PartNumber as vpn '
				'FROM VendorProducts '
				'JOIN Products ON VendorProducts.ProductID = Products.ID '
				'WHERE VendorID = %s AND (Products.UPC = %s OR Products.[Store UPC] = %s OR Products.MfgrPartNo = %s)'
		)

		values = [vendor_id, id, id, id]

		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			result = ascend.sql(
				query=vpn_query,
				values=values,
				as_dict=True
			)

			if len(result) > 0:
				# The "Vendor Product" virtual doctype names records as
				# "<PartNumber> (<VendorName>)" (see VendorProduct.NAME_EXPRESSION).
				# self.vendor already *is* the Vendor's name, so build the same
				# docname here rather than returning the bare part number.
				vendor_product_name = f"{result[0]['vpn']} ({self.vendor})"
				return ['vpn found', vendor_product_name]
			
			# Determine if Product exists for the scanned item.

			product_query = ('SELECT [Store UPC] as store_sku, UPC as upc '
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