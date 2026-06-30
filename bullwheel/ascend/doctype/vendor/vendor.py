# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class Vendor(AbstractVirtualDocType):
	TABLE_NAME = "Vendors"   # Ascend SQL table name
	SCHEMA_CONFIG = {
		'name': 'Name',
		'vendor_name': 'Name',
		'id': 'ID',
		'address': 'Address',
		'address2': 'Address2',
		'city': 'City',
		'state': 'State',
		'postal_code': 'ZIP',
		'phone_1': 'Phone',
		'fax': 'Fax',
		'email': 'EMail',
		'website': 'Website',
		'account_id': 'AccountID',
		'min_order': 'MinOrder',
		'free_shipping': 'FreeShipping',
		'sales_rep': 'SalesPerson',
		'terms': 'Terms',
		'ship_method': 'ShipVia',
		'creator_id': 'CreatorID',
		'modifier_id': 'ModifierID',
		'date_created': 'DateCreated',
		'date_modified': 'DateModified',
		'hide': 'Hide',
		'loc_from_id': 'LocFromID',
		'notes': 'Notes',
		'phone_2': 'Phone2',
		'date_last_downloaded': 'DateLastDownloaded',
		'country': 'Country',
		'row_version': 'Row_Version',
		'supplier_vendor_integration_id': 'SupplierVendorIntegrationId',
		'modifier_location_id': 'ModifierLocationId',
		'concurrency_token': 'ConcurrencyToken',
		'master_data_vendor_id': 'MasterDataVendorId',
		'msrp_level': 'MsrpLevel',
		'keep_product_updated': 'KeepProductUpdated',
		'supplier_integrator_id': 'SupplierIntegratorId',
		'supplier_integrator_config': 'SupplierIntegratorConfig',
		'catalog_id': 'CatalogId',
		'sync_purchase_orders': 'SyncPurchaseOrders',
		'is_default': 'IsDefault'
	}


# Link-field autocomplete hook (only if this DocType is a Link target)
# vendor_search = Vendor.make_search_function(display_fields=["vendor_name"])