# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.ascend.ascend_utilities import get_default_ascend_database


PRODUCT_TABLE = "Products"

# Columns searched when the user types in a Link field autocomplete.
SEARCH_COLUMNS = ["Description", "[Store UPC]", "UPC"]

# Maps DocType fieldname -> SQL Server column name.
# [Store UPC] requires bracket-quoting because the column name contains a space.
# `category` has no confirmed Products column — mapped to NULL until resolved.
# `sytle_number` preserves the existing misspelling in the DocType JSON.
FIELD_TO_COLUMN = {
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


class AscendProduct(Document):

	def db_insert(self, *args, **kwargs):
		raise NotImplementedError

	def load_from_db(self):
		"""Load a single Ascend Product from SQL Server by its ID and populate this document."""
		with MSSQLDatabase(server_document=get_default_ascend_database()) as database:
			result = database.sql(
				f"SELECT {SELECT_CLAUSE} FROM {PRODUCT_TABLE} WHERE ID = %s",
				[self.name],
				as_dict=True,
			)

		if not result:
			raise frappe.DoesNotExistError(f"Ascend Product '{self.name}' not found.")

		product = result[0]
		product["name"] = product["ascend_database_id"]

		super(Document, self).__init__(product)

	def db_update(self, *args, **kwargs):
		raise NotImplementedError

	def delete(self, *args, **kwargs):
		raise NotImplementedError

	@staticmethod
	def _extract_search_text(txt, or_filters):
		"""Return the raw search string from either a direct txt arg or Frappe's or_filters list."""
		if txt:
			return txt
		if or_filters:
			for filter_condition in or_filters:
				if len(filter_condition) >= 4 and filter_condition[2].lower() == "like":
					return filter_condition[3].strip("%")
		return None

	@staticmethod
	def get_list(filters=None, page_length=20, start=0, txt=None, or_filters=None, **_):
		"""Fetch a paginated, optionally filtered list of products from the Ascend Products table."""
		search_text = AscendProduct._extract_search_text(txt, or_filters)

		query = f"SELECT {SELECT_CLAUSE} FROM {PRODUCT_TABLE}"
		values = []

		if search_text:
			query += (
				" WHERE Description LIKE %s"
				" OR [Store UPC] LIKE %s"
				" OR UPC LIKE %s"
			)
			pattern = f"%{search_text}%"
			values = [pattern, pattern, pattern]

		query += " ORDER BY ID OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
		values += [start or 0, page_length or 20]

		with MSSQLDatabase(server_document=get_default_ascend_database()) as database:
			products = database.sql(query, values, as_dict=True)

		for product in products:
			product["name"] = product["ascend_database_id"]

		return products

	@staticmethod
	def get_count(filters=None, txt=None, or_filters=None, **_):
		"""Return the total number of products matching the current search text."""
		search_text = AscendProduct._extract_search_text(txt, or_filters)

		query = f"SELECT COUNT(*) FROM {PRODUCT_TABLE}"
		values = []

		if search_text:
			query += (
				" WHERE Description LIKE %s"
				" OR [Store UPC] LIKE %s"
				" OR UPC LIKE %s"
			)
			pattern = f"%{search_text}%"
			values = [pattern, pattern, pattern]

		with MSSQLDatabase(server_document=get_default_ascend_database()) as database:
			result = database.sql(query, values)

		return result[0][0] if result else 0

	@staticmethod
	def get_stats(**kwargs):
		pass
