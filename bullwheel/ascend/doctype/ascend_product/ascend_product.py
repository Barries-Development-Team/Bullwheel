# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""Ascend Product virtual DocType — reference implementation of the framework.

This controller demonstrates the Virtual DocType framework: it declares only
TABLE_NAME and SCHEMA_CONFIG, and inherits all query logic
(load_from_db, get_list, get_count, ordering, read-only guards) from
AbstractVirtualDocType. SCHEMA_CONFIG is the single source of truth — the
FIELD_TO_COLUMN map, SELECT clause, search columns, and Link autocomplete hook
are all derived from it.

See bullwheel/ascend/VIRTUAL_DOCTYPE_DEVELOPMENT.md for the full workflow.
"""

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class AscendProduct(AbstractVirtualDocType):
	"""Read-only virtual DocType mapping the Ascend RMS `Products` table."""

	TABLE_NAME = "Products"

	# Single source of truth: each Frappe fieldname -> SQL mapping and UI intent.
	#   sql_column — SQL Server column; bracket-quote names with spaces; None => SELECT NULL
	#   display    — "hidden" | "primary" | "secondary" | None (list-view / autocomplete exposure)
	#   searchable — include in the OR LIKE Link autocomplete search
	#
	# `name` maps Frappe's primary identifier to the SQL primary key column.
	# `category` has no confirmed Products column — NULL placeholder until resolved.
	# `[Store UPC]` and `[Year]` are bracket-quoted (space / reserved-word).
	SCHEMA_CONFIG = {
		"name":                      {"sql_column": "Products.ID",            "fieldtype": "Data",     "display": "hidden",    "searchable": False},
		"ascend_database_id":        {"sql_column": "Products.ID",            "fieldtype": "Data",     "display": "hidden",    "searchable": False},
		"description":               {"sql_column": "Description",   "fieldtype": "Data",     "display": "primary",   "searchable": True},
		"keyword":                   {"sql_column": "Keyword",       "fieldtype": "Data",     "display": None,        "searchable": False},
	"category":              	    {"sql_column": "cat.Topic",            "fieldtype": "Link",     "display": None,        "searchable": False},
		"quantity":                  {"sql_column": "Quantity",      "fieldtype": "Int",      "display": "secondary", "searchable": False},
		"brand":                     {"sql_column": "Brand",         "fieldtype": "Data",     "display": None,        "searchable": False},
		"color":                     {"sql_column": "Color",         "fieldtype": "Data",     "display": None,        "searchable": False},
		"size":                      {"sql_column": "Size",          "fieldtype": "Data",     "display": None,        "searchable": False},
		"style_number":              {"sql_column": "StyleNumber",   "fieldtype": "Data",     "display": None,        "searchable": False},
		"style_name":                {"sql_column": "StyleName",     "fieldtype": "Data",     "display": None,        "searchable": False},
		"gender":                    {"sql_column": "Gender",        "fieldtype": "Data",     "display": None,        "searchable": False},
		"season":                    {"sql_column": "Season",        "fieldtype": "Data",     "display": None,        "searchable": False},
		"year":                      {"sql_column": "[Year]",        "fieldtype": "Data",     "display": None,        "searchable": False},
		"price":                     {"sql_column": "Price",         "fieldtype": "Currency", "display": None,        "searchable": False},
		"estimated_cost":            {"sql_column": "EstCost",       "fieldtype": "Currency", "display": None,        "searchable": False},
		"average_cost":              {"sql_column": "AvgCost",       "fieldtype": "Currency", "display": None,        "searchable": False},
		"store_sku":                 {"sql_column": "[Store UPC]",   "fieldtype": "Data",     "display": "secondary", "searchable": True},
		"upc":                       {"sql_column": "UPC",           "fieldtype": "Data",     "display": None,        "searchable": True},
		"manufacturers_part_number": {"sql_column": "MfgrPartNo",    "fieldtype": "Data",     "display": None,        "searchable": False},
	}

	JOIN_CONFIG = [
    {
        "join":  "LEFT JOIN",                          # JOIN type
        "table": "Categories",                         # Table to join
        "alias": "cat",                                # Optional alias
        "on":    "Products.TopicID = cat.ID",          # Full ON condition
    }
]


# Link-field autocomplete hook. Registered in hooks.py under standard_queries as
# bullwheel.ascend.doctype.ascend_product.ascend_product.ascend_product_search.
# Each result is (name, description, store_sku).
ascend_product_search = AscendProduct.make_search_function(display_fields=["description", "store_sku"])
