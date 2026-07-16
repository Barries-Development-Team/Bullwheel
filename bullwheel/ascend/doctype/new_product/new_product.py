# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

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


class NewProduct(Document):
	def validate(self):
		pass


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
