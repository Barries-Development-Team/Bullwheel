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

A DocType named **`SQL Server`** has been created in the `barries` app. It represents a configured SQL Server connection and serves as the source of configuration data for the database handler.

### Fields

| Fieldname | Fieldtype | Notes |
|---|---|---|
| `server` | Data | IP address or hostname |
| `username` | Data | SQL Server login username |
| `password` | Password | Frappe encrypts automatically at rest |
| `database` | Data | Target database name |


### DocType Action Configuration

The action is defined in the DocType editor under the **Actions** table:

| Field | Value |
|---|---|
| Label | `Test Connection` |
| Action Type | `Server Action` |
| Action | `barries.barries.doctype.sql_server.sql_server.SQLServer.test_connection` |

> **Important:** The Action field requires the **full dotted path** to the method in Frappe v16. Using just `test_connection` produces the error: `Failed to get method for command test_connection with 'test_connection'`.

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
barries/
└── barries/
    └── database/
        ├── __init__.py       ← Registry / factory
        ├── base.py           ← (Decided against — see note below)
        ├── mssql.py          ← MSSQLDatabase class
        └── exceptions.py     ← Custom exception hierarchy
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

### `__init__.py` (Registry)

```python
from .mssql import MSSQLDatabase
from .exceptions import ConnectionError, QueryError, TransactionError

_registry: dict[str, MSSQLDatabase] = {}

def get_handler(server_name: str) -> MSSQLDatabase:
    if server_name not in _registry:
        _registry[server_name] = _init_handler(server_name)
    return _registry[server_name]

def _init_handler(server_name: str) -> MSSQLDatabase:
    import frappe
    doc = frappe.get_doc("SQL Server", server_name)
    return MSSQLDatabase(
        server=doc.server,
        username=doc.username,
        password=doc.get_password("password"),
        database=doc.database,
    )
```

### `mssql.py` — Full Implementation

```python
import pymssql
import frappe
from frappe.utils import CallbackManager, recursive_defaultdict
from barries.database.exceptions import ConnectionError, QueryError, TransactionError


class MSSQLDatabase:
    """
    SQL Server database handler for Barrie's external server connections.
    Mirrors the interface style of frappe.database.database.Database
    without inheriting its MariaDB-coupled implementation.
    """

    VARCHAR_LENGTH = 255
    MAX_COLUMN_LENGTH = 128

    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        database: str,
        timeout: int = 10,
    ):
        self.server = server
        self.username = username
        self.password = password
        self.current_database = database
        self.timeout = timeout
        self.connection = None
        self.cursor = None
        self.transaction_write_count = 0
        self.before_commit = CallbackManager()
        self.after_commit = CallbackManager()
        self.before_rollback = CallbackManager()
        self.after_rollback = CallbackManager()
        self.value_cache = recursive_defaultdict()
        self.logger = frappe.logger("mssql")

    def connect(self) -> None:
        """Open a connection to the SQL Server instance using the credentials
        provided at initialization, raising a ConnectionError if the attempt fails."""
        try:
            self.connection = pymssql.connect(
                server=self.server,
                user=self.username,
                password=self.password,
                database=self.current_database,
                timeout=self.timeout,
            )
            self.cursor = self.connection.cursor(as_dict=False)
        except pymssql.OperationalError as error:
            raise ConnectionError(
                f"Failed to connect to server '{self.server}': {error}"
            ) from error

    def close(self) -> None:
        """Close the active database connection and reset the connection
        and cursor attributes to None, mirroring frappe.db.close()."""
        if self.connection:
            self.connection.close()
            self.cursor = None
            self.connection = None

    def __enter__(self):
        """Open the connection when entering a `with` block, returning self
        so the handler is accessible via the `as` clause."""
        self.connect()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        """On exiting a `with` block, commit if no exception occurred or
        rollback if one did, then close the connection in either case."""
        if exception_type:
            self.rollback()
        else:
            self.commit()
        self.close()

    def sql(
        self,
        query: str,
        values: tuple | list | dict = (),
        *,
        as_dict: bool = False,
        as_list: bool = False,
        debug: bool = False,
        auto_commit: bool = False,
        pluck: bool = False,
    ) -> list:
        """Execute a raw SQL query against the active connection and return
        results in the requested format, mirroring the signature of frappe.db.sql().
        Connects automatically if no active connection exists."""
        if not self.connection:
            self.connect()

        if not isinstance(values, tuple | list | dict):
            values = (values,)

        if debug:
            self.logger.warning(f"Executing query: {query} | Values: {values}")

        try:
            self.cursor = self.connection.cursor(as_dict=as_dict)
            self.cursor.execute(query, values or None)

            if auto_commit:
                self.commit()

            if not self.cursor.description:
                return []

            result = self.cursor.fetchall()

            if pluck:
                return [row[0] for row in result]

            if as_list and not as_dict:
                return [[value for value in row] for row in result]

            return result

        except pymssql.DatabaseError as error:
            raise QueryError(
                f"Query execution failed: {error}\nQuery: {query}"
            ) from error

    def get_value(
        self,
        table: str,
        filters: dict | str,
        fieldname: str | list = "*",
        as_dict: bool = False,
        debug: bool = False,
    ):
        """Fetch a single value or row from the given table matching the
        provided filters, mirroring frappe.db.get_value(). Returns None if
        no matching record is found."""
        fields = fieldname if isinstance(fieldname, list) else [fieldname]
        columns = ", ".join(fields) if fieldname != "*" else "*"
        resolved_filters = filters if isinstance(filters, dict) else {"name": filters}
        where_clause, where_values = self._build_where_clause(resolved_filters)
        query = f"SELECT TOP 1 {columns} FROM {table} WHERE {where_clause}"
        result = self.sql(query, where_values, as_dict=as_dict, debug=debug)

        if not result:
            return None

        row = result[0]

        if as_dict or isinstance(fieldname, list) or fieldname == "*":
            return row

        return row[0] if not as_dict else row.get(fieldname)

    def get_all(
        self,
        table: str,
        filters: dict = None,
        fields: list = None,
        order_by: str = None,
        limit: int = None,
        as_dict: bool = True,
        debug: bool = False,
    ) -> list:
        """Fetch all rows from the given table matching the provided filters,
        mirroring frappe.db.get_all(). Returns an empty list if no rows match."""
        query, values = self._build_select_query(table, filters, fields, order_by, limit)
        return self.sql(query, values, as_dict=as_dict, debug=debug)

    def exists(self, table: str, filters: dict | str) -> bool:
        """Return True if at least one record matching the given filters exists
        in the table, mirroring frappe.db.exists()."""
        result = self.get_value(table, filters, fieldname="1")
        return result is not None

    def count(self, table: str, filters: dict = None, debug: bool = False) -> int:
        """Return the number of rows in the given table matching the provided
        filters, mirroring frappe.db.count()."""
        where_clause, values = (
            self._build_where_clause(filters) if filters else ("1=1", ())
        )
        query = f"SELECT COUNT(*) FROM {table} WHERE {where_clause}"
        result = self.sql(query, values, debug=debug)
        return result[0][0] if result else 0

    def insert(self, table: str, values: dict) -> None:
        """Insert a single row into the given table using the provided column-value
        dictionary, mirroring frappe.db.insert()."""
        columns = ", ".join(values.keys())
        placeholders = ", ".join(["%s"] * len(values))
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        self.sql(query, tuple(values.values()), as_dict=False)

    def set_value(
        self, table: str, filters: dict | str, field: str, value=None
    ) -> None:
        """Update a single field on all rows matching the given filters,
        mirroring frappe.db.set_value()."""
        resolved_filters = filters if isinstance(filters, dict) else {"name": filters}
        where_clause, where_values = self._build_where_clause(resolved_filters)
        query = f"UPDATE {table} SET {field} = %s WHERE {where_clause}"
        self.sql(query, (value,) + where_values, as_dict=False)

    def delete(self, table: str, filters: dict) -> None:
        """Delete all rows from the given table matching the given filters,
        mirroring frappe.db.delete()."""
        where_clause, values = self._build_where_clause(filters)
        query = f"DELETE FROM {table} WHERE {where_clause}"
        self.sql(query, values, as_dict=False)

    def begin(self) -> None:
        """Disable autocommit on the active connection to begin an explicit
        transaction, mirroring frappe.db.begin()."""
        if self.connection:
            self.connection.autocommit(False)

    def commit(self) -> None:
        """Commit the current transaction, fire registered commit callbacks,
        and clear the value cache, mirroring frappe.db.commit()."""
        if not self.connection:
            return
        try:
            self.before_commit.run()
            self.connection.commit()
            self.value_cache.clear()
            self.after_commit.run()
        except pymssql.DatabaseError as error:
            raise TransactionError(f"Commit failed: {error}") from error

    def rollback(self) -> None:
        """Roll back the current transaction, fire registered rollback callbacks,
        and clear the value cache, mirroring frappe.db.rollback()."""
        if not self.connection:
            return
        try:
            self.before_rollback.run()
            self.connection.rollback()
            self.value_cache.clear()
            self.after_rollback.run()
        except pymssql.DatabaseError as error:
            raise TransactionError(f"Rollback failed: {error}") from error

    def test_connection(self) -> bool:
        """Attempt to open a connection and execute a minimal query to verify
        that the server is reachable and credentials are valid. Always closes
        the connection before returning."""
        try:
            self.connect()
            self.sql("SELECT 1")
            return True
        except (ConnectionError, QueryError):
            return False
        finally:
            self.close()

    def _build_where_clause(self, filters: dict) -> tuple[str, tuple]:
        """Convert a dictionary of column-value pairs into a parameterized SQL
        WHERE clause string and a tuple of the corresponding values."""
        if not filters:
            return "1=1", ()
        clause = " AND ".join([f"{column} = %s" for column in filters.keys()])
        return clause, tuple(filters.values())

    def _build_select_query(
        self,
        table: str,
        filters: dict = None,
        fields: list = None,
        order_by: str = None,
        limit: int = None,
    ) -> tuple[str, tuple]:
        """Construct a parameterized SELECT query from the provided table name,
        filters, field list, ordering, and row limit. Uses SQL Server's TOP
        syntax rather than LIMIT, which is not supported by SQL Server."""
        columns = ", ".join(fields) if fields else "*"
        top_clause = f"TOP {limit} " if limit else ""
        query = f"SELECT {top_clause}{columns} FROM {table}"
        values = ()

        if filters:
            where_clause, values = self._build_where_clause(filters)
            query += f" WHERE {where_clause}"

        if order_by:
            query += f" ORDER BY {order_by}"

        return query, values
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

## Outstanding Items / Next Steps

The following were in progress or implied at the end of the conversation:

- `test_connection` DocType action was confirmed working after fixing the full dotted path in the Actions table
- `MSSQLDatabase` handler implementation is complete and documented
- The `barries` app's `database/` module structure is defined but individual files beyond `mssql.py` (`__init__.py`, `exceptions.py`) have not been fully written out — they exist as code snippets in conversation only
- `pymssql` needs to be added to `barries/requirements.txt` to survive container rebuilds

---

## Files Produced This Session

| File | Description |
|---|---|
| `SQLServer.py` | Full refactored `MSSQLDatabase` class |
| `MSSQLDatabase.md` | Public API documentation for `MSSQLDatabase` |
| `agent_context.md` | This file |
