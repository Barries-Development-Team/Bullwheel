# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# bullwheel/ascend/doctype/ascend_<thing>/ascend_<thing>.py
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class ProductCategory(AbstractVirtualDocType):
	TABLE_NAME = "Categories"
	SCHEMA_CONFIG = {
	'name': 'Categories.Topic',
	'database_id': 'Categories.ID',
	'parent_category': 'parent.Topic',
	'parent_id': 'Categories.ParentID',
	'other_id': 'Categories.OtherID',
	'category_name': 'Categories.Topic',
	'qbacct_type': 'Categories.QBAcctType',
	'qbincome': 'Categories.QBIncome',
	'qbinventory': 'Categories.QBInventory',
	'qbcogs': 'Categories.QBCOGS',
	'code': 'Categories.Code',
	'serialized': 'Categories.Serialized',
	'allow_schedule': 'Categories.AllowSchedule',
	'creator_id': 'Categories.CreatorID',
	'modifier_id': 'Categories.ModifierID',
	'date_created': 'Categories.DateCreated',
	'date_modified': 'Categories.DateModified',
	'hide': 'Categories.Hide',
	'loc_from_id': 'Categories.LocFromID',
	'trek_category': 'Categories.TrekCategory',
	'top_parent_id': 'Categories.TopParentID',
	'row_version': 'Categories.Row_Version',
	'concurrency_token': 'Categories.ConcurrencyToken',
	'rental': 'Categories.Rental'
	}

	JOIN_CONFIG = [
		{
        "join":  "LEFT JOIN",                          # JOIN type
        "table": "Categories",                         # Table to join
        "alias": "parent",                                # Optional alias
        "on":    "Categories.ParentID = parent.ParentID",          # Full ON condition
    	}	
	]