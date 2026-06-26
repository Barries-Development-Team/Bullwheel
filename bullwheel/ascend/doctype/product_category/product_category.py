# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# bullwheel/ascend/doctype/ascend_<thing>/ascend_<thing>.py
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class ProductCategory(AbstractVirtualDocType):
    TABLE_NAME = "Categories"
    SCHEMA_CONFIG = {
        "name": {
                "sql_column": "Topic",
                "fieldtype": "Data",
                "display": "hidden",
                "searchable": False,
        },
        "database_id": {
                "sql_column": "ID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "parent_id": {
                "sql_column": "ParentID",
                "fieldtype": "Link",
                "display": None,
                "searchable": False,
        },
        "other_id": {
                "sql_column": "OtherID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "category_name": {
                "sql_column": "Topic",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "qbacct_type": {
                "sql_column": "QBAcctType",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "qbincome": {
                "sql_column": "QBIncome",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "qbinventory": {
                "sql_column": "QBInventory",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "qbcogs": {
                "sql_column": "QBCOGS",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "code": {
                "sql_column": "Code",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "serialized": {
                "sql_column": "Serialized",
                "fieldtype": "Check",
                "display": None,
                "searchable": False,
        },
        "allow_schedule": {
                "sql_column": "AllowSchedule",
                "fieldtype": "Check",
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
        "trek_category": {
                "sql_column": "TrekCategory",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "top_parent_id": {
                "sql_column": "TopParentID",
                "fieldtype": "Data",
                "display": None,
                "searchable": False,
        },
        "row_version": {
                "sql_column": "Row_Version",
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
        "rental": {
                "sql_column": "Rental",
                "fieldtype": "Check",
                "display": None,
                "searchable": False,
        },
    }


# Link-field autocomplete hook (only if this DocType is a Link target)
# product_category_search = ProductCategory.make_search_function(display_fields=[""])