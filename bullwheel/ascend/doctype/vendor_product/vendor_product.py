# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class VendorProduct(AbstractVirtualDocType):
	TABLE_NAME = "VendorProducts"     # Ascend SQL table name
	JOIN_CONFIG: list = None          # Optional config for joining multiple tables. See Step 3b          
	SHOW_FIELD_WARNINGS: bool = True  # Display a warning to the console if frappe tries to lookup an unmapped field.
	NAME_EXPRESSION = "CONCAT(VendorProducts.PartNumber, ' (', Vendor.Name, ')')"  # Optional SQL expression to generate the 'name' field for the virtual doctype.
	SCHEMA_CONFIG = {
        'id': 'VendorProducts.ID',
        'vendor_id': 'VendorProducts.VendorID',
		'vendor': 'Vendor.Name',
        'product_id': 'VendorProducts.ProductID',
		'product': 'Product.[Store UPC]',
        'description': 'VendorProducts.Description',
        'part_number': 'VendorProducts.PartNumber',
        'cost': 'VendorProducts.Cost',
        'creator_id': 'VendorProducts.CreatorID',
        'modifier_id': 'VendorProducts.ModifierID',
        'date_created': 'VendorProducts.DateCreated',
        'date_modified': 'VendorProducts.DateModified',
        'hide': 'VendorProducts.Hide',
        'loc_from_id': 'VendorProducts.LocFromID',
        'row_version': 'VendorProducts.Row_Version',
        'case_quantity': 'VendorProducts.CaseQty',
        'case_upc': 'VendorProducts.CaseUPC',
        'case_msrp': 'VendorProducts.CaseMSRP',
        'modifier_location_id': 'VendorProducts.ModifierLocationID',
        'concurrency_token': 'VendorProducts.ConcurrencyToken',
        'has_pending_delta': 'VendorProducts.HasPendingDelta'
	}
	JOIN_CONFIG = [
    {
        "join":  "INNER JOIN",                          # JOIN type
        "table": "Vendors",                         # Table to join
        "alias": "Vendor",                                # Optional alias
        "on":    "VendorProducts.VendorID = Vendor.ID",          # Full ON condition
    },
	{
        "join":  "INNER JOIN",                          # JOIN type
        "table": "Products",                         # Table to join
        "alias": "Product",                                # Optional alias
        "on":    "VendorProducts.ProductID = Product.ID",          # Full ON condition
    }
	]