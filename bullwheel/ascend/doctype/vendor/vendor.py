# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class AscendThing(AbstractVirtualDocType):
    TABLE_NAME = "Vendors"   # Ascend SQL table name
    SCHEMA_CONFIG = {
        "name": {
                "sql_column": "Name",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "id": {
                "sql_column": "ID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "address": {
                "sql_column": "Address",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "address2": {
                "sql_column": "Address2",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "city": {
                "sql_column": "City",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "state": {
                "sql_column": "State",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "zip": {
                "sql_column": "ZIP",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "phone": {
                "sql_column": "Phone",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "fax": {
                "sql_column": "Fax",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "email": {
                "sql_column": "EMail",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "website": {
                "sql_column": "Website",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "account_id": {
                "sql_column": "AccountID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "min_order": {
                "sql_column": "MinOrder",
                "fieldtype": "Currency",
                "display": None,
                "searchable": False,
        },
        "free_shipping": {
                "sql_column": "FreeShipping",
                "fieldtype": "Currency",
                "display": None,
                "searchable": False,
        },
        "sales_person": {
                "sql_column": "SalesPerson",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "terms": {
                "sql_column": "Terms",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "ship_via": {
                "sql_column": "ShipVia",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "creator_id": {
                "sql_column": "CreatorID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "modifier_id": {
                "sql_column": "ModifierID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "date_created": {
                "sql_column": "DateCreated",
                "fieldtype": "Datetime",
                "display": None,
                "searchable": False,
        },
        "date_modified": {
                "sql_column": "DateModified",
                "fieldtype": "Datetime",
                "display": None,
                "searchable": False,
        },
        "hide": {
                "sql_column": "Hide",
                "fieldtype": "Check",
                "display": None,
                "searchable": False,
        },
        "loc_from_id": {
                "sql_column": "LocFromID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "notes": {
                "sql_column": "Notes",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "phone2": {
                "sql_column": "Phone2",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "date_last_downloaded": {
                "sql_column": "DateLastDownloaded",
                "fieldtype": "Datetime",
                "display": None,
                "searchable": False,
        },
        "country": {
                "sql_column": "Country",
                "fieldtype": "Int",
                "display": None,
                "searchable": False,
        },
        "row_version": {
                "sql_column": "Row_Version",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "supplier_vendor_integration_id": {
                "sql_column": "SupplierVendorIntegrationId",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "modifier_location_id": {
                "sql_column": "ModifierLocationId",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "concurrency_token": {
                "sql_column": "ConcurrencyToken",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "master_data_vendor_id": {
                "sql_column": "MasterDataVendorId",
                "fieldtype": "Int",
                "display": None,
                "searchable": False,
        },
        "msrp_level": {
                "sql_column": "MsrpLevel",
                "fieldtype": "Int",
                "display": None,
                "searchable": False,
        },
        "keep_product_updated": {
                "sql_column": "KeepProductUpdated",
                "fieldtype": "Check",
                "display": None,
                "searchable": False,
        },
        "supplier_integrator_id": {
                "sql_column": "SupplierIntegratorId",
                "fieldtype": "Int",
                "display": None,
                "searchable": False,
        },
        "supplier_integrator_config": {
                "sql_column": "SupplierIntegratorConfig",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "catalog_id": {
                "sql_column": "CatalogId",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "sync_purchase_orders": {
                "sql_column": "SyncPurchaseOrders",
                "fieldtype": "Check",
                "display": None,
                "searchable": False,
        },
        "is_default": {
                "sql_column": "IsDefault",
                "fieldtype": "Check",
                "display": None,
                "searchable": False,
        },
	}


# Link-field autocomplete hook (only if this DocType is a Link target)
ascend_thing_search = AscendThing.make_search_function(display_fields=["description"])