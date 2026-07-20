# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType
from bullwheel.bullwheel_core import get_default_ascend_database
from bullwheel.database.SQLServer import MSSQLDatabase


class VendorProduct(AbstractVirtualDocType):
	LABEL_RESOLUTION_FIELD = 'product'  # Link → Ascend Product; label prints resolve through it (see label_printing/resolution.py)
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
		'upc': 'Product.UPC',
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


def create_vendor_product(
	vendor_id, product_id, part_number, cost, description=None,
	case_quantity=None, case_upc=None, case_msrp=None,
):
	"""Insert one VendorProducts row into Ascend, linking a Product to a vendor that does not
	yet carry it (used by Order Receipt's vendor-link flow during receiving, and by New
	Product's insert for brand-new products). Kept as a raw parameterized INSERT, outside the
	read-only virtual doctype framework, because VendorProduct's NAME_EXPRESSION (a computed
	CONCAT of PartNumber and Vendor.Name) is not a real column and therefore cannot be produced
	by the framework's generic db_insert. Re-checks for an existing row for this vendor + part
	number inside the same connection, so the check and the insert commit or roll back together
	(see MSSQLDatabase.__exit__). Returns True when a row was inserted, False when an existing
	row was found and reused."""

	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		existing = ascend.sql(
			"SELECT ID FROM VendorProducts WHERE VendorID = %s AND PartNumber = %s",
			[vendor_id, part_number],
			as_dict=True,
		)
		if existing:
			return False

		ascend.sql(
			"INSERT INTO VendorProducts "
			"(ID, VendorID, ProductID, PartNumber, Cost, Description, CaseQty, CaseUPC, CaseMSRP, "
			"DateCreated, Hide, HasPendingDelta) "
			"VALUES (NEWID(), %s, %s, %s, %s, %s, %s, %s, %s, GETDATE(), 0, 0)",
			[vendor_id, product_id, part_number, cost, description, case_quantity, case_upc, case_msrp],
			as_dict=False,
		)

		inserted_row_count = ascend.cursor.rowcount
		if inserted_row_count != 1:
			frappe.throw(f"Insert into VendorProducts affected {inserted_row_count} rows instead of exactly one.")

		return True