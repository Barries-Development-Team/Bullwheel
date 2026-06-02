# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe

from bullwheel.database.SQLServer import MSSQLDatabase

# ── Schema Placeholders ────────────────────────────────────────────────────────
# Update these constants to match the actual Ascend RMS table and column names.

PRODUCT_TABLE = "Products"

FIELD_MAP = {
    "Description":              "Description",
    "Price":                    "Price",
    "Quantity":                 "Quantity",
    "UPC":                      "UPC",
    "SKU":                      "[Store UPC]",
    "Manufacturer Part Number": "MfgrPartNo",
    "Keyword":                  "Keyword",
    "Location":                 "Location",
    "Brand":                    "Brand",
    "Color":                    "Color",
    "Size":                     "Size",
    "Style Name":               "StyleName",
    "Style Number":             "StyleNumber",
    "Gender":                   "Gender",
    "Year":                     "Year",
    "Season":                   "Season",
}

# Columns searched when search_field is "default".
DEFAULT_SEARCH_COLUMNS = ["Description", "[Store UPC]", "UPC"]

# Columns returned and displayed in the results table.
RESULT_COLUMNS = ["Description", "[Store UPC] AS SKU", "UPC", "Brand", "Price", "Quantity", "Location"]


@frappe.whitelist()
def search_products(server_name: str, search_text: str, search_field: str = "default") -> list:
    """Query the Ascend RMS product table and return matching records for the
    given search text, optionally restricted to a specific column."""
    server_document = frappe.get_doc("SQL Server", server_name)

    with MSSQLDatabase(server_document) as database:
        columns = ", ".join(RESULT_COLUMNS)

        if search_field == "default":
            conditions = " OR ".join(
                [f"{column} LIKE %s" for column in DEFAULT_SEARCH_COLUMNS]
            )
            values = tuple([f"%{search_text}%"] * len(DEFAULT_SEARCH_COLUMNS))
        else:
            sql_column = FIELD_MAP.get(search_field, "Description")
            conditions = f"{sql_column} LIKE %s"
            values = (f"%{search_text}%",)

        query = f"SELECT {columns} FROM {PRODUCT_TABLE} WHERE {conditions}"
        return database.sql(query, values, as_dict=True)
