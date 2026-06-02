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

## Outstanding Items / Next Steps

- **Ascend schema verification** — confirm the placeholder column names in `ascend_products.py` against the actual `Products` table in Ascend RMS. Especially: `StyleName`, `StyleNumber`, `Keyword`, `Location`, `Gender`, `Year`, `Season`, `Price`, `Quantity`, `Brand`, `Color`, `Size`.
- **Result row limit** — `search_products` currently returns all matching rows. Consider adding a `TOP N` limit once the real query volume is known.
- **`pymssql` in requirements.txt** — verify `pymssql` is listed in `bullwheel/requirements.txt` so it survives container rebuilds.
