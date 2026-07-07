# Agent Context File
# Project: Barrie's "Bullwheel" App
# Generated from development conversation with Carter
# Date: 2026-05-26

---

## Developer Profile

- **Name:** Carter
- **Employer:** Barrie's Ski and Sports — a retail ski and sport shop focusing on skiing, biking, and water sports
- **Role:** Primary technical person; handles software development, customization, IT infrastructure
- **Languages:** Proficient in Python, C#, and C++; more experienced in Python for backend work
- **Education:** Computer science student at Idaho State University
- **Infrastructure:** Windows 11 workstation, personal TrueNAS home server, Docker Desktop, WSL2, Tailscale, Cloudflare Tunnels, Ascend RMS with local SQL Server.
- **Custom Frappe App:** `bullwheel` — a custom app built on Frappe Framework v16. Built to run in tandem with Ascend RMS.

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

### Key Constraints

- Must connect to and query **multiple Microsoft SQL Server instances** running natively on Windows machines on the local network
- **Multi-device access** is required (warehouse tablets, front desk PCs, manager laptops)
- **Ease of maintenance** is a top priority
- Self-hosted on Carter's own infrastructure — no cloud hosting
- Python is preferred for backend logic
- Internal business tool — no plans for public distribution

---

### Technology Stack: Frappe Framework + SQL Server (existing, native Windows)

**Frappe Framework** was selected for the following reasons:
- Backend is Python, with Javascript frontend.
- Easy deployment using **Frappe Docker**.
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

## Frappe Development Environment Details

- **Site name:** `barriesdev.localhost`
- **Developer mode:** Enabled
- **Docker Compose file location:** Managed by Frappe Docker.


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
| Python method added or modified only | `bench restart` |
| DocType fields or actions changed via editor | `bench --site barriesdev.localhost migrate` |

---

## Database Architecture

Bullwheel connects to external SQL Server instances through a single-layer architecture:

```
bullwheel/
└── bullwheel/
    ├── database/
        ├── SQLServer.py          ← MSSQLDatabase — connection / execution layer
        ├── exceptions.py         ← Custom exception hierarchy
        └── doctype/sql_server/   ← SQL Server DocType (stores credentials)
    
```

**`MSSQLDatabase` (`database/SQLServer.py`)**
The connection and execution primitive. Owns: connection lifecycle (`connect`, `close`, `__enter__`/`__exit__`), raw query execution (`sql`), transaction management (`commit`, `rollback`, `begin`), and health check (`test_connection`). The Virtual DocType Framework uses it directly for all Ascend queries — controllers write no SQL and do not interact with `MSSQLDatabase` directly.

**Virtual DocType controllers** (e.g. `ascend_product.py`) inherit from `AbstractVirtualDocType` and declare only a `SCHEMA_CONFIG` dict plus `TABLE_NAME` and `PRIMARY_KEY_COLUMN`. The base class derives `FIELD_TO_COLUMN`, the `SELECT` clause, and `SEARCH_COLUMNS` from `SCHEMA_CONFIG` and owns all query logic (`get_list`, `get_count`, `load_from_db`).

**`_build_where_clause`** (in `virtual_doctype_base.py`) handles both dict-format and list-format Frappe filters, operators `=`, `!=`, `<`, `<=`, `>`, `>=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, and appends OR LIKE search across `search_columns` when text is present.

### Design Note

`MSSQLDatabase` originally contained high-level query methods (`get_value`, `get_all`, `exists`, `count`, `insert`, `set_value`, `delete`) modeled after `frappe.db`. These were removed because their equality-only filter logic could not serve real Ascend queries (no LIKE, no OR, no bracket-quoted columns, no OFFSET pagination). A second layer, `AscendDatabase`, was introduced but has since been eliminated — all query-building logic now lives in `AbstractVirtualDocType` in `virtual_doctype_base.py`.

### `SQLServer.py` — Constructor

The constructor accepts a `SQL Server` Frappe document and an optional `timeout`. Password decryption is handled internally via `get_decrypted_password` so callers never touch credentials directly.

The Virtual DocType Framework (`AbstractVirtualDocType`) uses `MSSQLDatabase` directly for all Ascend queries.

```python
with MSSQLDatabase(server_document) as database:
    results = database.sql("SELECT ...", values, as_dict=True)
```

---

## Coding Style Conventions

These conventions were explicitly requested by Carter and should be maintained going forward:

1. **No acronyms or shorthand in names** — use full descriptive names
   - `connection` not `conn`
   - `cursor` not `cur`
   - `username` not `user`
   - `exception_type` not `exc_type`
   - `error` not `e`
   - `column` not `k`
   - `value` not `v`

2. **Non-trivial methods must have at least one sentence of inline documentation** explaining the method's purpose and basic functionality. Comments should be enclosed in triple quotes ("""example""") below function declaration.

3. **Parameterized queries always** — never string formatting for SQL values

4. **Context manager pattern preferred** over manual connection lifecycle management

---

## Performance Considerations: frappe.call vs frm.call

For performance-sensitive operations (e.g., rapid scanning of items into a table):

- **Prefer `frappe.call`** with whitelisted static methods over `frm.call` with document methods
- **Why:** `frm.call` requires instantiating a document on the server (costly); `frappe.call` to a static method avoids this overhead
- **Implementation:** Create required server-side functions as static, whitelisted methods. Pass needed values as client-side arguments instead of retrieving them from the document instance on the server

This pattern significantly reduces latency for high-frequency operations.

---

## Label Printing (Zebra / ZPL)

The **Label Printing** module prints to Zebra printers using **raw ZPL over a TCP socket** — no driver, spooler, or CUPS on the Bullwheel side. There is **no extra dependency**: the transport is Python's stdlib `socket`. Zebra printers listen on port **9100** and execute whatever ZPL bytes arrive.

The module deliberately mirrors the SQL Server handler pattern (`MSSQLDatabase`), so the same conventions apply.

**Connection methods** — the `Label Printer.connection_method` field (`Network` / `USB`) selects the socket endpoint; `ZebraPrinter` resolves it once in `__init__` into `target_host`/`target_port`:

- **Network** → the printer's own ZPL listener at `ip:port` (default `:9100`).
- **USB** → the **Bullwheel USB Print Service** at `connected_computer_address:9100`. The USB printer has no network port, so a small Windows-side relay (`usb_print_service/`) listens on TCP 9100 and forwards raw ZPL to the local printer via the Windows spooler (win32print RAW). From `ZebraPrinter`'s view both methods are identical — a fire-and-forget TCP send. The service port is fixed in `ZebraPrinter.USB_PRINT_SERVICE_PORT` (9100) and must match the service's `--port`.

**Files**

| File | Role |
|---|---|
| `label_printing/ZebraPrinter.py` | `ZebraPrinter` — the transport primitive (printer analog of `MSSQLDatabase`). Constructed from a `Label Printer` doc; resolves `target_host`/`target_port` from `connection_method`; context-manager `connect`/`close`; `send(zpl)`; `get_host_status()` / `test_connection()`. **No commit/rollback** — printing is fire-and-forget. |
| `label_printing/exceptions.py` | `PrinterException` base + `PrinterConnectionError`, `PrinterSendError`, `PrinterStatusError`. |
| `label_printing/doctype/label_printer/label_printer.py` | Whitelisted `test_connection(**kwargs)` (msgprint green/orange/red) and `print_zpl(printer_name, zpl)` — the app-wide print entry point; guards against `disabled` printers. |
| `label_printing/doctype/label_printer/label_printer.js` | **Test Connection** form button (copied from `sql_server.js`). |


**`Label Printer` DocType** — device config: `printer_name` (autoname, unique), `connection_method` (Network/USB), `connected_computer_address` (USB only), `ip`/`port` (Network only, default 9100), `timeout` (default 5s), `dpi`, `type` (Direct Thermal / Thermal Transfer), `location`, `disabled`. Network vs USB fields are toggled via `depends_on` / `mandatory_depends_on` on `connection_method`.

**Conventions**

- **Send raw ZPL only.** Callers supply the ZPL string; the handler is transport, not templating. ZPL *content generation* (label layouts from product data) is a separate, not-yet-built layer.
- **Print via the whitelisted `print_zpl`**, never by touching `ZebraPrinter` from client code. Example caller: the **Print Label** button in `warehouse_location.js` (prompts for a `Label Printer`, then calls `print_zpl` — the reference pattern for adding a print button to any DocType).
- **Health check uses `~HS` (Host Status).** `get_host_status` parses paper-out / paused / head-open flags. A silent target — a printer that doesn't reply, or the **send-only USB service** (which never returns status) — is treated as **reachable-but-unknown**, not a failure. So USB printers always report "reachable, status unknown"; network printers get full status.
- **Sanitize interpolated values** — strip `^` and `~` (ZPL command prefixes) from any user/data string placed into ZPL.
- **Geometry comes from the printer's `dpi`, resolved at build time.** ZPL positions are in dots, and ZPL cannot do arithmetic, so any dot dimension derived from inches (e.g. a 2" width = `2 * dpi`) must be computed where `dpi` is a real number. The label builder fetches the selected printer's `dpi` (`frappe.db.get_value('Label Printer', ...)`) and computes dimensions before assembling the ZPL — `print_zpl` stays pure transport and does no substitution.
- **Centering:** `^FB<label_width>,1,0,C` at `^FO0,y` centers **text** fields — but **not** barcodes. `^FB` never moves a barcode's bars; they always start at the `^FO` origin. Center a barcode manually: estimate its width (Code 128 ≈ `(11 * chars + 35) * module_width` dots) and set `^FO<(label_width - barcode_width) / 2>,y`.
- No default-printer concept yet; callers name the printer explicitly.


---

## Warehouse Location DocType

The **Warehouse Location** DocType lives in the `warehouse` module and represents physical locations in the warehouse. It uses a parent-child hierarchy with an `is_group` checkbox.

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

The `product` field on the Location Inventory child DocType is a standard Frappe **Link** field pointing to the `Ascend Product` virtual DocType. Products (~200,000 SKUs) live in the Ascend RMS SQL Server and are never replicated into MariaDB. The virtual DocType handler bridges them into native Frappe Link UX, enabling autocomplete and `fetch_from` auto-population. See the Ascend Product section below for the full field mapping and handler details.

---

## Ascend Product Virtual DocType — Field Mapping

The **`Ascend Product`** DocType (module: `Ascend`, `is_virtual = 1`) maps a subset of the Ascend RMS `Products` table to Frappe fields. Not every SQL column has a corresponding field — only the columns relevant to Bullwheel operations are surfaced. The controller's `load_from_db` / `get_list` methods translate between the SQL column names and the Frappe fieldnames using the mapping below.

**Key DocType properties:**
- `autoname = field:ascend_database_id` → the Frappe `name` (primary key) is the Ascend `ID` column
- `title_field = description`
- `ascend_database_id` is marked `unique`

## Virtual DocType Framework

A reusable framework for building read-only virtual DocTypes over Ascend SQL Server tables. It eliminates the per-controller boilerplate (`get_list`/`get_count`/`load_from_db`, hand-written `FIELD_TO_COLUMN`/`SELECT_CLAUSE`/`SEARCH_COLUMNS`, separate search hooks, and the recurring sorting bug). A new DocType needs only a `SCHEMA_CONFIG` dict and a three-attribute controller.

**Step-by-step guide:** `documentation/VIRTUAL_DOCTYPE_DEVELOPMENT.md`

**Files:**

| File | Role |
|---|---|
| `ascend/virtual_doctype_base.py` | `AbstractVirtualDocType` — inherit this. Derives constants from `SCHEMA_CONFIG`, inherits `load_from_db`/`get_list`/`get_count`, wires `order_by` through to SQL, and provides read-only guards + `make_search_function`. |
| `ascend/schema_introspection.py` | `introspect_table_schema` (queries `INFORMATION_SCHEMA.COLUMNS` via `MSSQLDatabase`), `suggest_schema_config`, `format_schema_table`. |
| `commands.py` | Bench CLI: `bench --site <site> introspect-schema --table <Table> [--suggest]`. |

**`SCHEMA_CONFIG`** — single source of truth, one entry per fieldname:

```python
SCHEMA_CONFIG = {
    "fieldname": "sql_column",
    # sql_column: bracket-quote names with spaces ([Store UPC]); None => SELECT NULL
}
```

Exactly one entry must map Frappe's `name` to `PRIMARY_KEY_COLUMN`.

**GUID primary keys:** SQL Server `uniqueidentifier` columns come back from pymssql as `uuid.UUID` objects. The base class runs every record through `normalize_record`, stringifying UUIDs so `name`, Link values, and filters work. Without this, a UUID-keyed virtual DocType raises `Unsupported filters type: UUID`.

**"Show Title in Link Fields" is supported on virtual DocTypes.** It used to crash: Frappe resolves link titles via `frappe.db.get_value`/`get_values`, which query a non-existent `tab<DocType>` table. Bullwheel now patches `Database.get_value`/`get_values` (`bullwheel/overrides/virtual_link_title.py`, applied once from `bullwheel/__init__.py`) so that name-based lookups on a virtual DocType resolve through the controller's `load_from_db` instead of the database. One choke point covers every path (form load, the `get_link_title` endpoint, version diff, print). Enable `show_title_field_in_link` + `title_field` normally. See `VIRTUAL_DOCTYPE_DEVELOPMENT.md` § Gotchas, and `documentation/VIRTUAL_LINK_TITLE_PATCH.md` for a full walkthrough of the patch.

**Sorting fix:** `AbstractVirtualDocType.get_list` parses Frappe's `order_by` (backtick-aware, so DocType names with spaces like `` `tabAscend Product` `` work), maps the fieldname to its SQL column via `field_to_column()`, and injects it directly into the SQL query. Unmapped fields (e.g. the default `creation`) fall back to ordering by `primary_key_field()`.

**Tests:** `ascend/test_schema_config_builder.py` (11 builder tests) and `ascend/test_virtual_doctype_base.py` (6 order-by/derivation tests). Both are fast `UnitTestCase`s with no DB dependency. Run: `bench --site <site> run-tests --app bullwheel`.