# Agent Context File
# Project: Barrie's "Bullwheel" App
# Generated from development conversation with Carter
# Date: 2026-05-26

---

## Developer Profile

- **Name:** Carter
- **Employer:** Barrie's Ski and Sports — a retail ski and sport shop focusing on skiing, biking, and water sports
- **Role:** Primary technical person; handles ERP migration, customization, IT infrastructure
- **Languages:** Proficient in C# and Python; more experienced in Python for backend work
- **Education:** Computer science student at Idaho State University
- **Infrastructure:** Windows 11 workstation, personal TrueNAS home server, Docker Desktop, WSL2, Tailscale, Cloudflare Tunnels, Ascend RMS.
- **Existing ERP:** ERPNext v16 test environment running via Frappe Manager (Docker) on WSL2, accessible at `erp.barriesoutlet.com`. Not currently deployed.
- **Custom Frappe App:** `barries` — a custom Frappe app built on ERPNext v16. Built to run in tandem with ERPNext. Will be replaced by Bullwheel.

---

## Project Overview: Bullwheel.

A warehouse and operations utility application for Barrie's Ski and Sports.

### Intended Features

1. Inventory Location tracking
2. Ski-binding pair tracking
3. Swap sales
4. Warehouse fetch / picklist handling — when an item is sold directly from the warehouse, adjust location and quantity appropriately
5. Inventory counting and scheduling — each day, assign warehouse staff an inventory bay count
6. Automated software updates — check GitHub for new releases and apply them
7. Easy feature additions — isolated branch workflow, heavy backend testing
8. Tagging
9. Automated online listings
10. Data backups
11. Receiving — count verification, tagging, import sheet generation for Ascend RMS
12. Automated changelog — accurate record of all code changes
13. Ascend RMS login and credential sync

### Key Constraints

- Must connect to and query **multiple Microsoft SQL Server instances** running natively on Windows machines on the local network
- **Multi-device access** is required (warehouse tablets, front desk PCs, manager laptops)
- **Ease of maintenance** is a top priority
- Self-hosted on Carter's own infrastructure — no cloud hosting
- Python is preferred for backend logic
- Internal business tool — no plans for public distribution

---

## Technology Stack Decision

### Evaluated Options

The following frameworks were evaluated:

| Framework | Verdict |
|---|---|
| Windows Forms | Eliminated — Windows-only, no multi-device |
| WPF | Eliminated — Windows-only, no multi-device |
| WinUI 3 | Eliminated — Windows-only |
| MAUI | Not selected |
| Blazor Server + FastAPI | Strong contender but requires C# + Python context switching |
| **Frappe Framework** | **Selected** |

### Final Stack: Frappe Framework + SQL Server (existing, native Windows)

**Frappe Framework** was selected for the following reasons:
- Backend is Python, with Javascript frontend.
- Easy deployment using the third party utility **Frappe Framework**.
- Intended to run on WSL and Docker Engine on Windows 11.
- "Batteries Included": Many desired features, like user authentication and email are built-in.


**SQL Server** remains running natively on Windows. The Bullwheel app connects to it over the local network via `pymssql`. No SQL Server containerization is planned or needed.


### Software License

All Rights Reserved with a private GitHub repository. No open source license. A copyright header in source files:

```python
# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.
```

---

## Parallel Work: Frappe App (`barries`)

Alongside the Bullwheel utility app, Carter is actively developing the `barries` Frappe app on ERPNext v16. This conversation focused specifically on building a **SQL Server database handler** inside the `barries` Frappe app to connect to external SQL Server instances on the local network.

---

## Frappe Environment Details

- **Frappe Manager version:** v0.19.0 (`fm` CLI tool by rtCamp)
- **Site name:** `barriesdev.localhost`
- **Developer mode:** Enabled
- **Docker Compose file location:** Managed by Frappe Manager, located alongside the site directory in WSL

### Relevant Docker Services (from `docker-compose.yml`)

| Service | Container Name | Image | Purpose |
|---|---|---|---|
| `frappe` | `fm__barriesdev_localhost__frappe` | `ghcr.io/rtcamp/frappe-manager-frappe:v0.19.0` | Main bench container |
| `nginx` | `fm__barriesdev_localhost__nginx` | `ghcr.io/rtcamp/frappe-manager-nginx:v0.19.0` | Reverse proxy |
| `socketio` | `fm__barriesdev_localhost__socketio` | `ghcr.io/rtcamp/frappe-manager-frappe:v0.19.0` | Socket.IO worker |
| `schedule` | `fm__barriesdev_localhost__schedule` | `ghcr.io/rtcamp/frappe-manager-frappe:v0.19.0` | Scheduler worker |
| `redis-cache` | `fm__barriesdev_localhost__redis-cache` | `redis:8-alpine` | Cache |
| `redis-queue` | `fm__barriesdev_localhost__redis-queue` | `redis:8-alpine` | Queue |

### Known Docker / WSL Issues

- VS Code `fm code` command fails because VS Code runs in Windows context and sees a different Docker context than WSL. **Fix:** Launch VS Code from within WSL using `code .` from the site directory. This gives VS Code the correct Docker socket context.
- Frappe Manager may overwrite `docker-compose.yml` on `fm` commands. Any manual edits should be versioned and documented.

### Python Library for SQL Server

`pymssql` was selected over `mssql-python` and `python-tds` for the following reasons:
- Bundles FreeTDS — **no OS-level ODBC driver installation required** inside the Docker container
- Installable purely via `pip` inside the bench environment
- Survives container rebuilds as long as it is listed in the app's `requirements.txt`
- Sufficient performance for routine business queries
- Larger community and more Stack Overflow resources than `python-tds`

Install inside bench:
```bash
cd /workspace/frappe-bench
./env/bin/pip install pymssql
```

---

## SQL Server DocType

A DocType named **`SQL Server`** lives in the **Bullwheel** app at `bullwheel/database/doctype/sql_server/`. It represents a configured SQL Server connection and is the source of credentials for the `MSSQLDatabase` handler.

### Fields (Bullwheel app — current)

| Fieldname | Fieldtype | Notes |
|---|---|---|
| `server_name` | Data | IP address or hostname (required) |
| `database_name` | Data | Target database name (required) |
| `authentication_method` | Select | "SQL Server Authentication" or "Windows Authentication (WIP)" (required) |
| `username` | Data | Shown only when SQL Server Authentication is selected |
| `password` | Password | Frappe encrypts automatically at rest; shown only when SQL Server Authentication is selected |
| `trust_server_certificate` | Check | Whether to trust the server certificate |

### Whitelisted Method

`test_connection` is a module-level `@frappe.whitelist()` function in `bullwheel/database/doctype/sql_server/sql_server.py` — **not** a method on the `SQLServer` Document class. It is called from the DocType form button via:

```
bullwheel.database.doctype.sql_server.sql_server.test_connection
```

### Bench Commands After Changes

| Change Type | Command |
|---|---|
| Python method added or modified only | `fm restart` |
| DocType fields or actions changed via editor | `fm migrate` |
| Both | `fm migrate` |

---

## Database Architecture

Bullwheel connects to external SQL Server instances through a single-layer architecture:

```
bullwheel/
└── bullwheel/
    ├── database/
    │   ├── SQLServer.py          ← MSSQLDatabase — connection / execution layer
    │   ├── exceptions.py         ← Custom exception hierarchy
    │   └── doctype/sql_server/   ← SQL Server DocType (stores credentials)
    └── ascend/
        └── AscendDatabase.py     ← Legacy — to be removed
```

**`MSSQLDatabase` (`database/SQLServer.py`)**
The connection and execution primitive. Owns: connection lifecycle (`connect`, `close`, `__enter__`/`__exit__`), raw query execution (`sql`), transaction management (`commit`, `rollback`, `begin`), and health check (`test_connection`). The Virtual DocType Framework uses it directly for all Ascend queries — controllers write no SQL and do not interact with `MSSQLDatabase` directly.

**Virtual DocType controllers** (e.g. `ascend_product.py`) inherit from `AbstractVirtualDocType` and declare only a `SCHEMA_CONFIG` dict plus `TABLE_NAME` and `PRIMARY_KEY_COLUMN`. The base class derives `FIELD_TO_COLUMN`, the `SELECT` clause, and `SEARCH_COLUMNS` from `SCHEMA_CONFIG` and owns all query logic (`get_list`, `get_count`, `load_from_db`).

```python
with MSSQLDatabase(get_default_ascend_database()) as ascend:
    results = ascend.sql(query=query, values=values, as_dict=True)
```

**`_build_where_clause`** (in `virtual_doctype_base.py`) handles both dict-format and list-format Frappe filters, operators `=`, `!=`, `<`, `<=`, `>`, `>=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, and appends OR LIKE search across `search_columns` when text is present.

### Design Note

`MSSQLDatabase` originally contained high-level query methods (`get_value`, `get_all`, `exists`, `count`, `insert`, `set_value`, `delete`) modeled after `frappe.db`. These were removed because their equality-only filter logic could not serve real Ascend queries (no LIKE, no OR, no bracket-quoted columns, no OFFSET pagination). A second layer, `AscendDatabase`, was introduced but has since been eliminated — all query-building logic now lives in `AbstractVirtualDocType` in `virtual_doctype_base.py`.

### `exceptions.py`

```python
class SQLServerException(Exception):
    """Base exception for all SQL Server errors."""
    pass

class ConnectionError(SQLServerException):
    """Raised when a connection cannot be established."""
    pass

class QueryError(SQLServerException):
    """Raised when a query fails."""
    pass

class TransactionError(SQLServerException):
    """Raised when a transaction operation fails."""
    pass
```

### `__init__.py`

Empty — no registry in Bullwheel. Callers instantiate `MSSQLDatabase` directly.

### `SQLServer.py` — Constructor

The constructor accepts a `SQL Server` Frappe document and an optional `timeout`. Password decryption is handled internally via `get_decrypted_password` so callers never touch credentials directly.

The Virtual DocType Framework (`AbstractVirtualDocType`) uses `MSSQLDatabase` directly for all Ascend queries.

```python
with MSSQLDatabase(server_document) as database:
    results = database.sql("SELECT ...", values, as_dict=True)
```

---

## Coding Style Conventions (Established This Session)

These conventions were explicitly requested by Carter and should be maintained going forward:

1. **No acronyms or shorthand in names** — use full descriptive names
   - `connection` not `conn`
   - `cursor` not `cur`
   - `username` not `user`
   - `exception_type` not `exc_type`
   - `error` not `e`
   - `column` not `k`
   - `value` not `v`

2. **Non-trivial methods must have at least one sentence of inline documentation** explaining the method's purpose and basic functionality

3. **Parameterized queries always** — never string formatting for SQL values

4. **Context manager pattern preferred** over manual connection lifecycle management

---

## Ascend RMS — SQL Server Schema (Partial)

These column names were discovered during development. The authoritative field mapping now lives in `FIELD_TO_COLUMN` in `ascend_product.py`. Update both this table and that dict as more of the schema is confirmed.

| Logical Field | SQL Column Name | Notes |
|---|---|---|
| Product table | `Products` | Top-level table name |
| Description | `Description` | Primary item name / search field |
| SKU (Ascend internal) | `[Store UPC]` | Bracket-quoted — contains a space |
| UPC | `UPC` | Standard barcode |
| Manufacturer Part No. | `MfgrPartNo` | |
| Brand, Color, Size, Location, Keyword, Gender, Year, Season, Style Name, Style Number, Price, Quantity | `Brand`, `Color`, `Size`, `Location`, `Keyword`, `Gender`, `Year`, `Season`, `StyleName`, `StyleNumber`, `Price`, `Quantity` | Unverified — placeholders |

---

## Warehouse Location DocType

The **Warehouse Location** DocType lives in the `barries` module and represents physical locations in the warehouse. It uses a parent-child hierarchy with an `is_group` checkbox.

- **Group locations** (e.g., "Basement, Aisle B") are containers for child locations. They cannot directly hold inventory.
- **Leaf locations** (e.g., "Bin 234, Shelf 123") can hold inventory via a child table `inventory_items` (SKU + quantity pairs).

### Inventory Terminology

When discussing what's stored in a location, preferred terms are:
- **Inventory composition** / **inventory mix** — specific products/SKUs and quantities
- **Bin contents** / **location contents** — what's physically stored at a specific bin
- **On-hand inventory** — actual physical stock present (vs. system records)

### Hierarchy Validation

`depends_on` controls field *visibility* only — it does not delete data. Enforcing the group/leaf constraint requires code-based validation.

**Recommended approach: combine server-side validation with a client-side `onchange` handler.**

Server-side (`warehouse_location.py`):

```python
from frappe.model.document import Document

class WarehouseLocation(Document):
    def validate(self):
        # Groups cannot hold inventory directly
        if self.is_group and self.inventory_items:
            self.inventory_items = []
            frappe.msgprint("Inventory cleared: Group locations cannot hold items directly")

        # Leaves cannot have children
        if not self.is_group:
            child_count = frappe.db.count('Warehouse Location',
                                           filters={'parent_location': self.name})
            if child_count > 0:
                frappe.throw(f"Cannot uncheck 'Is Group': This location has {child_count} child location(s)")

        # Parent must be a group
        if self.parent_location:
            parent = frappe.get_doc('Warehouse Location', self.parent_location)
            if not parent.is_group:
                frappe.throw(f"Parent location '{self.parent_location}' must be a group location")
```

Client-side (`warehouse_location.js`) — for immediate UX feedback:

```javascript
frappe.ui.form.on('Warehouse Location', {
    is_group: function(frm) {
        if (frm.doc.is_group && frm.doc.inventory_items.length) {
            frm.clear_table('inventory_items');
            frm.refresh_field('inventory_items');
            frappe.msgprint("Inventory cleared for group location");
        }
    }
});
```

The `validate()` method is automatically invoked by Frappe before save, submit, or amend — no extra wiring is required.

**File locations:**

```
barries/
└── doctype/
    └── warehouse_location/
        ├── warehouse_location.py      ← validate() method here
        ├── warehouse_location.json    ← DocType definition
        └── warehouse_location.js     ← client-side onchange handler
```

---

## Product Reference Architecture

The `product` field on the Location Inventory child DocType is a standard Frappe **Link** field pointing to the `Ascend Product` virtual DocType. Products (~20,000 SKUs) live in the Ascend RMS SQL Server and are never replicated into MariaDB. The virtual DocType handler bridges them into native Frappe Link UX, enabling autocomplete and `fetch_from` auto-population. See the Ascend Product section below for the full field mapping and handler details.

---

## Ascend Product Virtual DocType — Field Mapping

The **`Ascend Product`** DocType (module: `Ascend`, `is_virtual = 1`) maps a subset of the Ascend RMS `Products` table to Frappe fields. Not every SQL column has a corresponding field — only the columns relevant to Bullwheel operations are surfaced. The controller's `load_from_db` / `get_list` methods translate between the SQL column names and the Frappe fieldnames using the mapping below.

**Key DocType properties:**
- `autoname = field:ascend_database_id` → the Frappe `name` (primary key) is the Ascend `ID` column
- `title_field = description`
- `ascend_database_id` is marked `unique`

### Mapped Fields

**Product Details section**

| DocType Fieldname | Fieldtype | Ascend SQL Column | Notes |
|---|---|---|---|
| `description` | Data | `Description` | Title field; primary search column |
| `keyword` | Data | `Keyword` | |
| `category` | Data | *(unresolved)* | ⚠ No direct `Category` column in `Products`. Candidate: `Division` — **unconfirmed**, needs verification against Ascend |
| `quantity` | Int | `Quantity` | On-hand count |
| `brand` | Data | `Brand` | |
| `color` | Data | `Color` | |
| `size` | Data | `Size` | |
| `sytle_number` | Data | `StyleNumber` | ⚠ Fieldname is misspelled `sytle_number` (label "Sytle Number"). SQL column is correctly spelled `StyleNumber`. The mapping dict must bridge the typo. Consider renaming the field to `style_number` for consistency |
| `style_name` | Data | `StyleName` | |
| `gender` | Data | `Gender` | |
| `season` | Data | `Season` | |
| `year` | Data | `[Year]` | Bracket-quoted in SQL — avoids conflict with SQL Server's `YEAR()` function |

**Pricing section**

| DocType Fieldname | Fieldtype | Ascend SQL Column | Notes |
|---|---|---|---|
| `price` | Currency | `Price` | |
| `estimated_cost` | Currency | `EstCost` | |
| `average_cost` | Currency | `AvgCost` | |

**ID's and Barcodes section**

| DocType Fieldname | Fieldtype | Ascend SQL Column | Notes |
|---|---|---|---|
| `ascend_database_id` | Data (unique) | `ID` | Primary key / `name` via autoname; the stable identifier for `load_from_db` lookups |
| `store_sku` | Data | `Store UPC` | ⚠ Column contains a space — must be bracket-quoted as `[Store UPC]` in all SQL |
| `upc` | Data | `UPC` | Standard barcode |
| `manufacturers_part_number` | Data | `MfgrPartNo` | |

### Unmapped `Products` Columns

These columns exist in the Ascend `Products` table but are intentionally **not** surfaced as DocType fields. Listed here for reference if any are needed later:

`ReorderLevel`, `Maximum`, `Commission`, `Location`, `Other`, `Division`, `eCommerce`, `Min2`, `Max2`, `NoLabel`, `NonInventory`, `ApptLength`, `DateCreated`, `DateModified`, `Hide`, `DolCom`, `Comments`, `DateQtyChng`, `PrintLabelsByDivision`, `DateReconciled`, `LastCost`, `HasPendingDelta`

### Handler Implementation

**File:** `bullwheel/ascend/doctype/ascend_product/ascend_product.py`

`AscendProduct` now inherits from `AbstractVirtualDocType` and is the **reference implementation** of the Virtual DocType Framework. The entire controller is:

- `TABLE_NAME = "Products"`, `PRIMARY_KEY_COLUMN = "ID"`
- a single `SCHEMA_CONFIG` dict (one entry per field: `sql_column`, `fieldtype`, `display`, `searchable`)
- one line binding the search hook: `ascend_product_search = AscendProduct.make_search_function(display_fields=["description", "store_sku"])`

`FIELD_TO_COLUMN`, the `SELECT` clause, and `SEARCH_COLUMNS` (`["Description", "[Store UPC]", "UPC"]`) are **derived** from `SCHEMA_CONFIG` by the base class — they are no longer hand-written. `get_list`, `get_count`, `load_from_db`, and the read-only guards are all inherited. `get_list` resolves the list view's `order_by` to a real SQL `ORDER BY` (the prior sorting bug is fixed for every subclass).

The framework still maps `name → ID` (so Frappe's meta-field resolves in filters) and still projects `category` as `NULL` until its `Products` column is confirmed.

**Resolved during the framework refactor:** the controller previously keyed its constants on the misspelled `sytle_number` while the DocType JSON field is `style_number` — a latent mismatch that meant the style number never populated. `SCHEMA_CONFIG` now uses `style_number` (→ `StyleNumber`), matching the JSON.

---

## Virtual DocType Framework

A reusable framework for building read-only virtual DocTypes over Ascend SQL Server tables. It eliminates the per-controller boilerplate (`get_list`/`get_count`/`load_from_db`, hand-written `FIELD_TO_COLUMN`/`SELECT_CLAUSE`/`SEARCH_COLUMNS`, separate search hooks, and the recurring sorting bug). A new DocType needs only a `SCHEMA_CONFIG` dict and a three-attribute controller.

**Step-by-step guide:** `documentation/VIRTUAL_DOCTYPE_DEVELOPMENT.md`

**Files:**

| File | Role |
|---|---|
| `ascend/virtual_doctype_base.py` | `AbstractVirtualDocType` — inherit this. Derives constants from `SCHEMA_CONFIG`, inherits `load_from_db`/`get_list`/`get_count`, wires `order_by` through to SQL, and provides read-only guards + `make_search_function`. |
| `ascend/schema_config_builder.py` | Pure converters: `build_field_to_column`, `build_select_clause`, `build_search_columns`, `build_json_schema`, `find_primary_key_field`, `validate_schema_config`. No DB access. |
| `ascend/schema_introspection.py` | `introspect_table_schema` (queries `INFORMATION_SCHEMA.COLUMNS` via `MSSQLDatabase`), `suggest_schema_config`, `format_schema_table`. |
| `ascend/search_hook_helper.py` | `create_virtual_doctype_search` — generates the Link-autocomplete function registered under `standard_queries`. |
| `commands.py` | Bench CLI: `bench --site <site> introspect-schema --table <Table> [--suggest]`. |

**`SCHEMA_CONFIG`** — single source of truth, one entry per fieldname:

```python
SCHEMA_CONFIG = {
    "description": {"sql_column": "Description", "fieldtype": "Data", "display": "primary", "searchable": True},
    # sql_column: bracket-quote names with spaces ([Store UPC]); None => SELECT NULL
    # display:    "hidden" | "primary" | "secondary" | None  (list/autocomplete exposure)
    # searchable: include in the OR LIKE Link autocomplete
}
```

Exactly one entry must map `sql_column` to `PRIMARY_KEY_COLUMN`; that field becomes Frappe's `name`.

**GUID primary keys:** SQL Server `uniqueidentifier` columns come back from pymssql as `uuid.UUID` objects. The base class runs every record through `normalize_record` (in `schema_config_builder.py`), stringifying UUIDs so `name`, Link values, and filters work. Without this, a UUID-keyed virtual DocType raises `Unsupported filters type: UUID`.

**"Show Title in Link Fields" is supported on virtual DocTypes.** It used to crash: Frappe resolves link titles via `frappe.db.get_value`/`get_values`, which query a non-existent `tab<DocType>` table. Bullwheel now patches `Database.get_value`/`get_values` (`bullwheel/overrides/virtual_link_title.py`, applied once from `bullwheel/__init__.py`) so that name-based lookups on a virtual DocType resolve through the controller's `load_from_db` instead of the database. One choke point covers every path (form load, the `get_link_title` endpoint, version diff, print). Enable `show_title_field_in_link` + `title_field` normally. See `VIRTUAL_DOCTYPE_DEVELOPMENT.md` § Gotchas.

**Sorting fix:** `AbstractVirtualDocType.get_list` parses Frappe's `order_by` (backtick-aware, so DocType names with spaces like `` `tabAscend Product` `` work), maps the fieldname to its SQL column via `field_to_column()`, and injects it directly into the SQL query. Unmapped fields (e.g. the default `creation`) fall back to ordering by `primary_key_field()`.

**Tests:** `ascend/test_schema_config_builder.py` (11 builder tests) and `ascend/test_virtual_doctype_base.py` (6 order-by/derivation tests). Both are fast `UnitTestCase`s with no DB dependency. Run: `bench --site <site> run-tests --app bullwheel`.

---

## Outstanding Items / Next Steps

- ✅ **Product reference architecture** — Virtual DocType (Option A) selected and implemented. `Ascend Product` handler (`get_list`, `get_count`, `load_from_db`) live in `ascend_product.py`. Bug fixed in `ascend_utilities.py` (`frappe.db.get_doc` → `frappe.get_doc`).
- **`category` column source** — `Ascend Product.category` maps to `NULL` in `SELECT_CLAUSE`. Verify whether `Division` or another `Products` column is the correct source, then update `FIELD_TO_COLUMN` and `SELECT_CLAUSE` in `ascend_product.py`.
- ✅ **`sytle_number` rename (controller side)** — `SCHEMA_CONFIG` now keys on `style_number` (→ `StyleNumber`), matching the DocType JSON field. The JSON already uses `style_number`. If the field label still reads "Sytle Number", fix it in the DocType editor and run `fm migrate`.
- **Remove `AscendDatabase.py`** — `ascend/AscendDatabase.py` is legacy code, superseded by query logic in `AbstractVirtualDocType`. Delete the file once no remaining imports reference it.
- **Ascend schema verification** — confirm `StyleName`, `StyleNumber`, `Keyword`, `Gender`, `[Year]`, `Season`, `EstCost`, `AvgCost` against the live `Products` table. Update `FIELD_TO_COLUMN` and `SELECT_CLAUSE` if any column names differ.
- **`pymssql` in requirements.txt** — verify `pymssql` is listed in `bullwheel/requirements.txt` so it survives container rebuilds.
- **Warehouse Location implementation** — implement combined server-side `validate()` and client-side `onchange` handler for the inventory child table.
