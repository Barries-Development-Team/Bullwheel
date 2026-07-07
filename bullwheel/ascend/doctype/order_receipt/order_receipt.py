# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database
from bullwheel.ascend.doctype.vendor.vendor import Vendor

# FOR DEBUGGING
from time import perf_counter


class OrderReceipt(Document):
	pass

	
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