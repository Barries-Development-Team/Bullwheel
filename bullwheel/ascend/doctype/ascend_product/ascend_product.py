# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from bullwheel.ascend.AscendDatabase import AscendDatabase
from bullwheel.ascend.ascend_utilities import get_default_ascend_database


PRODUCT_TABLE = "Products"

# Columns searched when the user types in a Link field autocomplete.
SEARCH_COLUMNS = ["Description", "[Store UPC]", "UPC"]

# Maps DocType fieldname -> SQL Server column name.
# "name" maps the Frappe meta-field to the table's primary key for filter resolution.
# [Store UPC] requires bracket-quoting because the column name contains a space.
# `category` has no confirmed Products column — mapped to NULL until resolved.
# `sytle_number` preserves the existing misspelling in the DocType JSON.
FIELD_TO_COLUMN = {
	"name":                      "ID",
	"ascend_database_id":        "ID",
	"description":               "Description",
	"keyword":                   "Keyword",
	"quantity":                  "Quantity",
	"brand":                     "Brand",
	"color":                     "Color",
	"size":                      "Size",
	"sytle_number":              "StyleNumber",
	"style_name":                "StyleName",
	"gender":                    "Gender",
	"season":                    "Season",
	"year":                      "[Year]",
	"price":                     "Price",
	"estimated_cost":            "EstCost",
	"average_cost":              "AvgCost",
	"store_sku":                 "[Store UPC]",
	"upc":                       "UPC",
	"manufacturers_part_number": "MfgrPartNo",
}

# Pre-built SELECT clause with AS aliases so result dicts use fieldnames directly.
# category has no confirmed SQL column — NULL placeholder until schema is verified.
SELECT_CLAUSE = (
	"ID AS ascend_database_id, "
	"Description AS description, "
	"Keyword AS keyword, "
	"NULL AS category, "
	"Quantity AS quantity, "
	"Brand AS brand, "
	"Color AS color, "
	"Size AS size, "
	"StyleNumber AS sytle_number, "
	"StyleName AS style_name, "
	"Gender AS gender, "
	"Season AS season, "
	"[Year] AS year, "
	"Price AS price, "
	"EstCost AS estimated_cost, "
	"AvgCost AS average_cost, "
	"[Store UPC] AS store_sku, "
	"UPC AS upc, "
	"MfgrPartNo AS manufacturers_part_number"
)


@frappe.whitelist()
def ascend_product_search(_doctype, txt, _searchfield, start, page_length, _filters, as_dict=False):
	"""Custom Link field search registered via standard_queries hook.

	Bypasses frappe.get_list so that search_widget's as_list/relevance_sorter
	pipeline — which is incompatible with virtual DocType results — is never reached.
	Returns tuples (id, description, store_sku) when as_dict=False, frappe._dict
	objects when as_dict=True.
	"""
	_ = _doctype, _searchfield, _filters  # required positional args from the standard_queries contract

	with AscendDatabase(get_default_ascend_database()) as ascend:
		products = ascend.get_list(
			PRODUCT_TABLE, SELECT_CLAUSE, "ID", FIELD_TO_COLUMN,
			search_columns=SEARCH_COLUMNS,
			page_length=int(page_length),
			start=int(start),
			txt=txt,
		)

	if as_dict:
		return [frappe._dict({**product, "name": product["ascend_database_id"]}) for product in products]

	return [
		(product["ascend_database_id"], product["description"] or "", product["store_sku"] or "")
		for product in products
	]


class AscendProduct(Document):

	def db_insert(self, *args, **kwargs):
		raise NotImplementedError

	def load_from_db(self):
		"""Load a single Ascend Product from SQL Server by its ID and populate this document."""
		with AscendDatabase(get_default_ascend_database()) as ascend:
			product = ascend.get_record(PRODUCT_TABLE, SELECT_CLAUSE, "ID", self.name)

		if not product:
			raise frappe.DoesNotExistError(f"Ascend Product '{self.name}' not found.")

		super(Document, self).__init__(frappe._dict({**product, "name": product["ascend_database_id"]}))

	def db_update(self, *args, **kwargs):
		raise NotImplementedError

	def delete(self, *args, **kwargs):
		raise NotImplementedError

	@staticmethod
	def get_list(filters=None, page_length=20, start=0, txt=None, or_filters=None, **_) -> list:
		"""Fetch a paginated, optionally filtered list of products from the Ascend Products table."""
		with AscendDatabase(get_default_ascend_database()) as ascend:
			products = ascend.get_list(
				PRODUCT_TABLE, SELECT_CLAUSE, "ID", FIELD_TO_COLUMN,
				filters=filters,
				search_columns=SEARCH_COLUMNS,
				page_length=page_length,
				start=start,
				txt=txt,
				or_filters=or_filters,
			)

		return [
			frappe._dict({**product, "name": product["ascend_database_id"]})
			for product in products
		]

	@staticmethod
	def get_count(filters=None, txt=None, or_filters=None, **_):
		"""Return the total number of products matching the current filters or search text."""
		with AscendDatabase(get_default_ascend_database()) as ascend:
			return ascend.count_records(
				PRODUCT_TABLE, FIELD_TO_COLUMN,
				filters=filters,
				search_columns=SEARCH_COLUMNS,
				txt=txt,
				or_filters=or_filters,
			)

	@staticmethod
	def get_stats(**_):
		pass
