# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class Vendor(AbstractVirtualDocType):
	TABLE_NAME = "Vendors"   # Ascend SQL table name
	SCHEMA_CONFIG = {
		'name':                           {'column': 'Name'},
		'vendor_name':                    {'column': 'Name'},
		'id':                             {'column': 'ID', 'static': True},
		'address':                        {'column': 'Address'},
		'address2':                       {'column': 'Address2'},
		'city':                           {'column': 'City'},
		'state':                          {'column': 'State'},
		'postal_code':                    {'column': 'ZIP'},
		'phone_1':                        {'column': 'Phone'},
		'fax':                            {'column': 'Fax'},
		'email':                          {'column': 'EMail'},
		'website':                        {'column': 'Website'},
		'account_id':                     {'column': 'AccountID'},
		'min_order':                      {'column': 'MinOrder'},
		'free_shipping':                  {'column': 'FreeShipping'},
		'sales_rep':                      {'column': 'SalesPerson'},
		'terms':                          {'column': 'Terms'},
		'ship_method':                    {'column': 'ShipVia'},
		'creator_id':                     {'column': 'CreatorID', 'static': True},
		'modifier_id':                    {'column': 'ModifierID'},
		'date_created':                   {'column': 'DateCreated', 'static': True},
		'date_modified':                  {'column': 'DateModified'},
		'hide':                           {'column': 'Hide'},
		'loc_from_id':                    {'column': 'LocFromID'},
		'notes':                          {'column': 'Notes'},
		'phone_2':                        {'column': 'Phone2'},
		'date_last_downloaded':           {'column': 'DateLastDownloaded'},
		'country':                        {'column': 'Country'},
		'row_version':                    {'column': 'Row_Version'},
		'supplier_vendor_integration_id': {'column': 'SupplierVendorIntegrationId'},
		'modifier_location_id':           {'column': 'ModifierLocationId'},
		'concurrency_token':              {'column': 'ConcurrencyToken'},
		'master_data_vendor_id':          {'column': 'MasterDataVendorId'},
		'msrp_level':                     {'column': 'MsrpLevel'},
		'keep_product_updated':           {'column': 'KeepProductUpdated'},
		'supplier_integrator_id':         {'column': 'SupplierIntegratorId'},
		'supplier_integrator_config':     {'column': 'SupplierIntegratorConfig'},
		'catalog_id':                     {'column': 'CatalogId'},
		'sync_purchase_orders':           {'column': 'SyncPurchaseOrders'},
		'is_default':                     {'column': 'IsDefault'},
	}