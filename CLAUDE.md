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

## MSSQLDatabase Handler

The core database handler is implemented in:

```
bullwheel/
└── bullwheel/
    └── database/
        ├── __init__.py       ← Empty (no registry in Bullwheel — instantiate directly)
        ├── SQLServer.py      ← MSSQLDatabase class
        ├── exceptions.py     ← Custom exception hierarchy
        └── doctype/
            └── sql_server/   ← SQL Server DocType
```

### Design Decisions

**Frappe's `Database` base class was evaluated and rejected** as a parent class. After reading `frappe/database/database.py` in full, it was determined to be too deeply coupled to MariaDB internals:
- `frappe.qb` (PyPika query builder) is hardcoded throughout high-level methods
- Transaction SQL uses MariaDB-specific syntax (`COMMIT AND CHAIN`, `START TRANSACTION`)
- `setup_type_map()` is called in `__init__` and requires MariaDB/Postgres type mappings
- Many abstract methods assume MariaDB/Postgres internals

**Decision:** `MSSQLDatabase` is a standalone class that mirrors the *interface style* of `frappe.db` without inheriting its implementation.

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

```python
server_document = frappe.get_doc("SQL Server", server_name)

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

These column names were discovered when building the product search page. Update as more of the schema is explored.

| Logical Field | SQL Column Name | Notes |
|---|---|---|
| Product table | `Products` | Top-level table name |
| Description | `Description` | Primary item name / search field |
| SKU (Ascend internal) | `[Store UPC]` | Bracket-quoted — contains a space |
| UPC | `UPC` | Standard barcode |
| Manufacturer Part No. | `MfgrPartNo` | |
| Brand, Color, Size, Location, Keyword, Gender, Year, Season, Style Name, Style Number, Price, Quantity | `Brand`, `Color`, `Size`, `Location`, `Keyword`, `Gender`, `Year`, `Season`, `StyleName`, `StyleNumber`, `Price`, `Quantity` | Unverified — placeholders |

> The `RESULT_COLUMNS` list in `ascend_products.py` uses `"[Store UPC] AS SKU"` to alias the bracket-quoted column back to `SKU` so the frontend dict key is clean.

---

## Ascend Products Page

**Files:**
- `bullwheel/ascend/page/ascend_products/ascend_products.py` — backend API
- `bullwheel/ascend/page/ascend_products/ascend_products.js` — page UI

### Backend (`ascend_products.py`)

Schema constants (`PRODUCT_TABLE`, `FIELD_MAP`, `DEFAULT_SEARCH_COLUMNS`, `RESULT_COLUMNS`) are defined at the top of the file — the only section that needs updating as the Ascend schema is confirmed.

Whitelisted method: `search_products(server_name, search_text, search_field="default")`
- Full path: `bullwheel.ascend.page.ascend_products.ascend_products.search_products`
- `search_field="default"` → OR LIKE across `DEFAULT_SEARCH_COLUMNS` (Description, [Store UPC], UPC)
- Specific field → single-column LIKE via `FIELD_MAP`
- Uses `MSSQLDatabase` context manager; returns `list[dict]`

### Frontend (`ascend_products.js`)

Three `page.add_field()` controls in the page toolbar:
1. **Server** — `fieldtype: 'Link'`, `options: 'SQL Server'` — auto-completes against SQL Server DocType records
2. **Search Field** — `fieldtype: 'Select'` — Default or any individual Ascend field
3. **Search** — `fieldtype: 'Data'` — free text; Enter key triggers search

`page.set_primary_action('Search', ...)` calls `perform_search(page)`.

Results rendered as a Bootstrap `table table-bordered table-hover` in `$(page.main)`. Result dict keys match `RESULT_COLUMNS` column aliases (e.g., `SKU` from the `AS SKU` alias).

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

## Product Reference Architecture (Decision Pending)

The **Location Inventory** child DocType needs a `product` field that references products from the remote Ascend RMS MS SQL Server (~20,000 SKUs). These records do not exist in the Frappe/MariaDB database. Two viable paths were identified.

### Why Standard Frappe Field Types Fall Short

| Field Type | Problem |
|---|---|
| **Link** (standard) | Assumes target is a Frappe DocType in MariaDB — would require replicating 20k products |
| **Select / Autocomplete** | Cannot hold thousands of dynamic options |
| **Dynamic Link** | Solves polymorphic references across Frappe DocTypes, not external data |
| **Data (unvalidated)** | Plain text; no autocomplete, no referential checking |

### Option A: Virtual DocType + Link Field (Recommended for broad use)

Create an `Ascend Product` DocType with `is_virtual = 1`. Implement controller methods (`get_list`, `get_count`, `load_from_db`) to fetch from SQL Server via `MSSQLDatabase`. The `product` field becomes a standard **Link** field pointing to `Ascend Product`.

**Advantages:**
- Products behave as native Frappe entities throughout the app
- Link autocomplete works out of the box (routed to `get_list`)
- `fetch_from` enables read-only columns (description, price, brand) in the inventory line to auto-populate
- `frappe.get_doc("Ascend Product", sku)` works
- Reusable across picklists, swaps, receiving, automated listings

**Disadvantages:**
- Requires careful implementation of virtual DocType controller methods (search widget's `txt`/`limit`/filter shape)
- Link validation queries SQL Server on every save
- Each autocomplete keystroke triggers a query — needs debouncing and `TOP`/limit
- Some standard list-view features won't fully work with virtual data
- Stable unique identifier needed as virtual `name` (likely `[Store UPC]`/SKU)

### Option B: Data Field + Custom Autocomplete + Server-side Validation

Store the SKU as a **Data** field. Attach client-side autocomplete in the grid using the existing `search_products` whitelisted method from `ascend_products.py`. Validate existence in Warehouse Location's `validate()` via `MSSQLDatabase`.

**Advantages:**
- Simpler; reuses existing `ascend_products` search infrastructure
- Full control over query and autocomplete behavior
- Lower risk; fewer Frappe framework edge cases

**Disadvantages:**
- Not Frappe-idiomatic; loses native Link UX
- No `fetch_from` (can't auto-populate description/price)
- No clickable product reference
- Must hand-roll the autocomplete UI for grid fields
- Less reusable if products are referenced elsewhere

### Decision Framework

- **Choose Option A** if products will be referenced throughout Bullwheel (picklists, swaps, receiving, automated listings). Virtual DocType pays compounding dividends via `fetch_from` and native Link UX.
- **Choose Option B** if product references only ever live in this one child table, or if implementation complexity is a constraint.

**Status: Option A selected (2026-06-02).** The `Ascend Product` virtual DocType has been scaffolded in the `Ascend` module (`is_virtual = 1`, `autoname = field:ascend_database_id`, `title_field = description`). See the field mapping section below.

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
| `year` | Data | `Year` | |

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

### Implementation Notes

- The field-to-column mapping should live as a single dict (e.g. `FIELD_TO_COLUMN`) at the top of the DocType controller so `load_from_db` and `get_list` share one source of truth. This mirrors the schema-constants pattern already used in `ascend_products.py`.
- `[Store UPC]` requires bracket-quoting; build SELECT lists with `[Store UPC] AS store_sku` to keep result dict keys aligned with fieldnames.
- Two items need resolution before the mapping is final: the `category` column source, and the `sytle_number` → `style_number` rename.
- `Currency` fields (`price`, `estimated_cost`, `average_cost`) map from SQL `money`/`decimal` columns — confirm no precision loss when casting through `pymssql`.

---

## Outstanding Items / Next Steps

- **Ascend schema verification** — confirm the placeholder column names in `ascend_products.py` against the actual `Products` table in Ascend RMS. Especially: `StyleName`, `StyleNumber`, `Keyword`, `Location`, `Gender`, `Year`, `Season`, `Price`, `Quantity`, `Brand`, `Color`, `Size`.
- **Result row limit** — `search_products` currently returns all matching rows. Consider adding a `TOP N` limit once the real query volume is known.
- **`pymssql` in requirements.txt** — verify `pymssql` is listed in `bullwheel/requirements.txt` so it survives container rebuilds.
- **Product reference decision** — ✅ Resolved: Option A (Virtual DocType). `Ascend Product` scaffolded; implement `load_from_db` / `get_list` / `get_count` against `MSSQLDatabase`.
- **`category` column source** — `Ascend Product.category` has no confirmed `Products` column. Verify whether it maps to `Division` or another source.
- **`sytle_number` rename** — fieldname is misspelled; rename to `style_number` and update the field-order/mapping dict.
- **Warehouse Location implementation** — implement combined server-side `validate()` and client-side `onchange` handler now that the product reference approach is decided.
