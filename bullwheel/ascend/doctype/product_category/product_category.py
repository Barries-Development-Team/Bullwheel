# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# bullwheel/ascend/doctype/ascend_<thing>/ascend_<thing>.py
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class ProductCategory(AbstractVirtualDocType):
	TABLE_NAME = "Categories"
	SCHEMA_CONFIG = {
		'name':              {'column': 'Topic'},
		'database_id':       {'column': 'ID', 'static': True},
		'parent_category':   {'table': 'parent', 'column': 'Topic'},
		'other_id':          {'column': 'OtherID'},
		'category_name':     {'column': 'Topic'},
		'qbacct_type':       {'column': 'QBAcctType'},
		'qbincome':          {'column': 'QBIncome'},
		'qbinventory':       {'column': 'QBInventory'},
		'qbcogs':            {'column': 'QBCOGS'},
		'code':              {'column': 'Code'},
		'serialized':        {'column': 'Serialized'},
		'allow_schedule':    {'column': 'AllowSchedule'},
		'creator_id':        {'column': 'CreatorID', 'static': True},
		'modifier_id':       {'column': 'ModifierID'},
		'date_created':      {'column': 'DateCreated', 'static': True},
		'date_modified':     {'column': 'DateModified'},
		'hide':              {'column': 'Hide'},
		'loc_from_id':       {'column': 'LocFromID'},
		'trek_category':     {'column': 'TrekCategory'},
		'top_parent_id':     {'column': 'TopParentID'},
		'row_version':       {'column': 'Row_Version'},
		'concurrency_token': {'column': 'ConcurrencyToken'},
		'rental':            {'column': 'Rental'},
	}

	JOIN_CONFIG = [
		{
        "join":  "LEFT JOIN",                          # JOIN type
        "table": "Categories",                         # Table to join
        "alias": "parent",                                # Optional alias
        "on":    "Categories.ParentID = parent.ID",          # Full ON condition
    	}	
	]