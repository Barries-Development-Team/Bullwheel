# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe
from frappe import _

from barries.database import get_handler
from barries.database.exceptions import SQLServerException


# --- Ascend schema configuration ------------------------------------------------
# Maps the logical field names used by the Product Search page to the actual
# column names in the Ascend SQL Server database. Adjust the right-hand values to
# match your real Ascend schema. Everything here is a trusted, server-side
# constant: the table name and these column names are the ONLY identifiers ever
# interpolated into a SQL string. Every value that originates from the user is
# always passed as a bound parameter, never interpolated.

PRODUCT_TABLE = "Products"

# logical_name -> actual SQL Server column name
COLUMN_MAP = {
    "description": "Description",
    "price": "Price",
    "quantity": "Quantity",
    "sku": "SKU",
    "upc": "UPC",
    "manufacturer_part_number": "MfgPartNumber",
    "keyword": "Keyword",
    "brand": "Brand",
    "color": "Color",
    "size": "Size",
    "style_name": "StyleName",
    "style_number": "StyleNumber",
    "gender": "Gender",
    "year": "Year",
    "season": "Season",
    "location": "Location",
}

# Fields the user is allowed to search against, in dropdown order.
# logical_name -> human-readable label shown in the field dropdown.
SEARCHABLE_FIELDS = {
    "description": "Description",
    "sku": "SKU",
    "upc": "UPC",
    "manufacturer_part_number": "Mfg Part Number",
    "keyword": "Keyword",
    "brand": "Brand",
    "style_name": "Style Name",
    "style_number": "Style Number",
    "color": "Color",
    "size": "Size",
    "gender": "Gender",
    "year": "Year",
    "season": "Season",
    "location": "Location",
}

# Sentinel value representing the default multi-field search.
DEFAULT_SEARCH_VALUE = "__default__"
DEFAULT_SEARCH_LABEL = "Description, SKU & UPC (default)"

# Fields searched when the user has not picked a specific field.
DEFAULT_SEARCH_FIELDS = ["description", "sku", "upc"]

# Logical fields returned for each matching row and rendered in the result list.
RESULT_FIELDS = [
    "description",
    "price",
    "quantity",
    "sku",
    "upc",
    "brand",
    "location",
    "size",
    "color",
]

DEFAULT_LIMIT = 100
MAXIMUM_LIMIT = 500

# Character used as the LIKE ESCAPE character so that wildcard characters typed
# by the user are matched literally rather than treated as LIKE wildcards.
LIKE_ESCAPE_CHARACTER = "!"


@frappe.whitelist()
def get_search_config():
    """Return everything the Product Search page needs to build its controls:
    the list of searchable fields (with the default multi-field option first)
    and the names of every configured SQL Server connection. Called once when
    the page loads so the field list lives in exactly one place (this module)."""
    fields = [{"value": DEFAULT_SEARCH_VALUE, "label": DEFAULT_SEARCH_LABEL}]
    fields.extend(
        {"value": logical_name, "label": label}
        for logical_name, label in SEARCHABLE_FIELDS.items()
    )
    servers = frappe.get_all("SQL Server", pluck="name", order_by="name asc")
    return {"fields": fields, "servers": servers}


@frappe.whitelist()
def search_products(search_term, field=None, server_name=None, limit=DEFAULT_LIMIT):
    """Search the Ascend product table for rows whose chosen field (or the
    default Description/SKU/UPC set) contains the given search term, returning a
    list of dictionaries keyed by the logical field names in RESULT_FIELDS.

    All user input is bound as query parameters; only the validated, server-side
    column constants are interpolated into the SQL string."""
    search_term = (search_term or "").strip()
    if not search_term:
        return []

    resolved_limit = _resolve_limit(limit)
    resolved_server = _resolve_server(server_name)
    search_fields = _resolve_search_fields(field)

    select_clause = ", ".join(
        f"[{COLUMN_MAP[logical_name]}] AS [{logical_name}]"
        for logical_name in RESULT_FIELDS
    )
    where_clause = " OR ".join(
        f"[{COLUMN_MAP[logical_name]}] LIKE %s ESCAPE '{LIKE_ESCAPE_CHARACTER}'"
        for logical_name in search_fields
    )
    query = (
        f"SELECT TOP {resolved_limit} {select_clause} "
        f"FROM [{PRODUCT_TABLE}] "
        f"WHERE {where_clause} "
        f"ORDER BY [{COLUMN_MAP['description']}]"
    )

    pattern = f"%{_escape_like_term(search_term)}%"
    values = tuple(pattern for _ in search_fields)

    try:
        handler = get_handler(resolved_server)
        with handler:
            rows = handler.sql(query, values, as_dict=True)
    except SQLServerException as error:
        frappe.throw(_("Inventory search failed: {0}").format(str(error)))

    return rows


def _resolve_limit(limit) -> int:
    """Coerce the requested row limit to a safe integer within bounds, falling
    back to the default if it is missing or not a number."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAXIMUM_LIMIT))


def _resolve_server(server_name) -> str:
    """Validate the requested SQL Server connection name, or pick the only
    configured one if the caller did not specify a server. Raises a clear error
    when there is no connection, an unknown connection, or an ambiguous choice."""
    if server_name:
        if not frappe.db.exists("SQL Server", server_name):
            frappe.throw(
                _("SQL Server connection '{0}' does not exist.").format(server_name)
            )
        return server_name

    servers = frappe.get_all("SQL Server", pluck="name", limit=2)
    if not servers:
        frappe.throw(
            _("No SQL Server connection is configured. Create a SQL Server record first.")
        )
    if len(servers) > 1:
        frappe.throw(_("Multiple SQL Server connections exist. Please choose one."))
    return servers[0]


def _resolve_search_fields(field) -> list:
    """Return the list of logical field names to search. An empty value or the
    default sentinel maps to the default multi-field set; any other value must be
    a known searchable field, otherwise an error is raised. This allowlist check
    is what makes it safe to interpolate the resulting column names into SQL."""
    if not field or field == DEFAULT_SEARCH_VALUE:
        return DEFAULT_SEARCH_FIELDS
    if field not in SEARCHABLE_FIELDS:
        frappe.throw(_("Unknown search field: {0}").format(field))
    return [field]


def _escape_like_term(term: str) -> str:
    """Escape the LIKE wildcard characters in a user-supplied search term so that
    they are matched literally. The escape character itself is escaped first so it
    is not doubled when the other characters add their own escape prefix."""
    for character in (LIKE_ESCAPE_CHARACTER, "%", "_", "[", "]"):
        term = term.replace(character, f"{LIKE_ESCAPE_CHARACTER}{character}")
    return term
