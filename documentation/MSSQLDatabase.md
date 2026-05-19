# MSSQLDatabase

A SQL Server database handler for connecting to external SQL Server instances from within a Frappe app. Since the Frappe framework does not naitively support Microsoft SQL Server, this functionality is required for the application to communicate with the Ascend server. Mirrors the interface style of `frappe.db` without inheriting its MariaDB-coupled implementation.

---

## Installation & Import

```python
from barries.database.mssql import MSSQLDatabase
```

Requires `pymssql` to be installed in the bench environment:

```bash
cd /workspace/frappe-bench
./env/bin/pip install pymssql
```

---

## Basic Usage

### Context Manager (Recommended)

The preferred way to use `MSSQLDatabase` is as a context manager. The connection is opened automatically on entry and closed on exit. If an exception occurs inside the block, the transaction is rolled back automatically. If the block completes cleanly, it is committed automatically.

```python
with MSSQLDatabase(
    server="192.168.x.x",
    username="username",
    password="password",
    database="Ascend",
) as database:
    items = database.get_all("Users", filters={"Active": True})
```

### Manual Connection

If you need to manage the connection lifecycle yourself:

```python
database = MSSQLDatabase(
    server="192.168.1.100",
    username="sa",
    password="your-password",
    database="BarriesDB",
)

database.connect()

try:
    database.insert("AuditLog", {"Action": "test", "ItemID": "ITEM-001"})
    database.commit()
except Exception:
    database.rollback()
finally:
    database.close()
```

### Multi-Server Usage via Registry

When working with multiple SQL Server instances, use the registry in `barries.database` to retrieve named handlers tied to `SQL Server` DocType records:

```python
from barries.database import get_handler

with get_handler("Production") as production_database:
    items = production_database.get_all("Inventory")

with get_handler("Development") as development_database:
    development_database.insert("TestLog", {"Message": "hello"})
```

---

## Constructor

```python
MSSQLDatabase(
    server: str,
    username: str,
    password: str,
    database: str,
    timeout: int = 10,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `server` | `str` | required | IP address or hostname of the SQL Server instance |
| `username` | `str` | required | SQL Server login username |
| `password` | `str` | required | SQL Server login password |
| `database` | `str` | required | Name of the database to connect to |
| `timeout` | `int` | `10` | Seconds before a connection attempt times out |

---

## Connection Methods

### `connect()`

Opens a connection to the SQL Server instance. Called automatically when using the context manager or `sql()`. Raises `ConnectionError` if the connection attempt fails.

```python
database.connect()
```

### `close()`

Closes the active connection and resets the connection and cursor to `None`. Always called automatically on context manager exit.

```python
database.close()
```

### `test_connection() → bool`

Opens a connection, executes a minimal `SELECT 1` query, and returns `True` if successful or `False` if any error occurs. Always closes the connection before returning, making it safe to call at any time.

```python
if database.test_connection():
    print("Server is reachable")
else:
    print("Connection failed")
```

---

## Query Methods

### `sql(query, values, *, as_dict, as_list, debug, auto_commit, pluck) → list`

The core query executor. All other query methods route through `sql()` internally. Executes a raw SQL query and returns results in the requested format. Connects automatically if no active connection exists.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | required | Raw SQL query string |
| `values` | `tuple \| list \| dict` | `()` | Parameterized values substituted into the query |
| `as_dict` | `bool` | `False` | Return rows as `{"column": value}` dictionaries |
| `as_list` | `bool` | `False` | Return rows as plain lists rather than tuples |
| `debug` | `bool` | `False` | Log the query and values to the Frappe logger |
| `auto_commit` | `bool` | `False` | Commit immediately after execution |
| `pluck` | `bool` | `False` | Return only the first column of each row as a flat list |

```python
# Basic select
rows = database.sql("SELECT * FROM Inventory WHERE Location = %s", ("Warehouse A",))

# Return as dictionaries
rows = database.sql(
    "SELECT * FROM Inventory WHERE Location = %s",
    ("Warehouse A",),
    as_dict=True,
)

# Pluck a single column as a flat list
names = database.sql("SELECT ItemID FROM Inventory", pluck=True)
# → ["ITEM-001", "ITEM-002", "ITEM-003"]

# Non-query (INSERT / UPDATE / DELETE) — returns empty list
database.sql(
    "UPDATE Inventory SET Quantity = %s WHERE ItemID = %s",
    (25, "ITEM-001"),
)
```

> **Note:** Always use parameterized queries with `%s` placeholders rather than string formatting. This prevents SQL injection and ensures correct type handling.

---

### `get_value(table, filters, fieldname, as_dict, debug) → Any`

Fetches a single value or row from the given table. Returns `None` if no matching record is found. Mirrors `frappe.db.get_value()`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `table` | `str` | required | Table name |
| `filters` | `dict \| str` | required | Column-value filter dict, or a bare string matched against `name` |
| `fieldname` | `str \| list` | `"*"` | Column name, list of column names, or `"*"` for all columns |
| `as_dict` | `bool` | `False` | Return the row as a dictionary |
| `debug` | `bool` | `False` | Log the query to the Frappe logger |

```python
# Fetch a single field value
quantity = database.get_value("Inventory", {"ItemID": "ITEM-001"}, "Quantity")
# → 25

# Fetch multiple fields as a dict
item = database.get_value(
    "Inventory",
    {"ItemID": "ITEM-001"},
    ["ItemID", "Quantity", "Location"],
    as_dict=True,
)
# → {"ItemID": "ITEM-001", "Quantity": 25, "Location": "Warehouse A"}

# Fetch a full row using a bare string filter against `name`
item = database.get_value("Inventory", "ITEM-001", as_dict=True)

# Returns None if not found
result = database.get_value("Inventory", {"ItemID": "NONEXISTENT"}, "Quantity")
# → None
```

---

### `get_all(table, filters, fields, order_by, limit, as_dict, debug) → list`

Fetches all rows from the given table matching the provided filters. Returns an empty list if no rows match. Mirrors `frappe.db.get_all()`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `table` | `str` | required | Table name |
| `filters` | `dict` | `None` | Column-value filter dict. Omit to fetch all rows |
| `fields` | `list` | `None` | List of column names to return. Omit for all columns |
| `order_by` | `str` | `None` | Column name to order results by |
| `limit` | `int` | `None` | Maximum number of rows to return |
| `as_dict` | `bool` | `True` | Return rows as dictionaries |
| `debug` | `bool` | `False` | Log the query to the Frappe logger |

```python
# Fetch all items in a location
items = database.get_all("Inventory", filters={"Location": "Warehouse A"})

# Fetch specific fields
items = database.get_all(
    "Inventory",
    filters={"Location": "Warehouse A"},
    fields=["ItemID", "Quantity"],
    order_by="Quantity",
    limit=50,
)

# Fetch all rows with no filters
all_items = database.get_all("Inventory")
```

---

### `exists(table, filters) → bool`

Returns `True` if at least one record matching the given filters exists in the table, `False` otherwise. Mirrors `frappe.db.exists()`.

```python
if database.exists("Inventory", {"ItemID": "ITEM-001"}):
    print("Item exists")

# Also accepts a bare string matched against `name`
if database.exists("Inventory", "ITEM-001"):
    print("Item exists")
```

---

### `count(table, filters, debug) → int`

Returns the number of rows in the given table matching the provided filters. Mirrors `frappe.db.count()`.

```python
# Count all rows
total = database.count("Inventory")

# Count with filters
warehouse_count = database.count("Inventory", filters={"Location": "Warehouse A"})
```

---

### `insert(table, values) → None`

Inserts a single row into the given table using a column-value dictionary. Mirrors `frappe.db.insert()`. Does not commit automatically — call `commit()` or use the context manager.

```python
database.insert("AuditLog", {
    "Action": "quantity_update",
    "ItemID": "ITEM-001",
    "Timestamp": "2026-05-19 10:00:00",
})
database.commit()
```

---

### `set_value(table, filters, field, value) → None`

Updates a single field on all rows matching the given filters. Mirrors `frappe.db.set_value()`. Does not commit automatically.

```python
# Update by filter dict
database.set_value("Inventory", {"ItemID": "ITEM-001"}, "Quantity", 25)

# Update by bare string matched against `name`
database.set_value("Inventory", "ITEM-001", "Location", "Warehouse B")

database.commit()
```

---

### `delete(table, filters) → None`

Deletes all rows from the given table matching the provided filters. Mirrors `frappe.db.delete()`. Does not commit automatically.

```python
database.delete("AuditLog", {"ItemID": "ITEM-001"})
database.commit()
```

---

## Transaction Methods

Transactions are managed automatically when using the context manager. Use these methods directly only when managing the connection lifecycle manually.

### `begin() → None`

Disables autocommit on the active connection to begin an explicit transaction.

```python
database.begin()
```

### `commit() → None`

Commits the current transaction, fires all registered `before_commit` and `after_commit` callbacks, and clears the value cache. Raises `TransactionError` if the commit fails.

```python
database.commit()
```

### `rollback() → None`

Rolls back the current transaction, fires all registered `before_rollback` and `after_rollback` callbacks, and clears the value cache. Raises `TransactionError` if the rollback fails.

```python
database.rollback()
```

---

## Transaction Callbacks

Callback managers allow external code to register functions that fire automatically at transaction boundaries without modifying the handler itself. This mirrors Frappe's own `frappe.db.before_commit` hook system.

| Attribute | Fires |
|---|---|
| `before_commit` | Immediately before `commit()` calls `connection.commit()` |
| `after_commit` | Immediately after a successful commit |
| `before_rollback` | Immediately before `rollback()` calls `connection.rollback()` |
| `after_rollback` | Immediately after a successful rollback |

```python
database = get_handler("Production")

# Invalidate a cache entry before every commit
database.before_commit.add(lambda: cache.delete("inventory_summary"))

# Log every successful commit
database.after_commit.add(
    lambda: frappe.logger().info("SQL Server transaction committed")
)

# These fire automatically on the next commit
with database:
    database.set_value("Inventory", "ITEM-001", "Quantity", 25)
```

---

## Error Handling

All exceptions raised by `MSSQLDatabase` are defined in `barries.database.exceptions`:

| Exception | Raised When |
|---|---|
| `ConnectionError` | `connect()` fails — server unreachable, bad credentials, timeout |
| `QueryError` | `sql()` fails — syntax error, missing table or column |
| `TransactionError` | `commit()` or `rollback()` fails |

```python
from barries.database.exceptions import ConnectionError, QueryError, TransactionError

try:
    with get_handler("Production") as database:
        database.insert("Inventory", {"ItemID": "ITEM-999", "Quantity": 10})
except ConnectionError as error:
    frappe.log_error(f"Could not connect: {error}")
except QueryError as error:
    frappe.log_error(f"Query failed: {error}")
except TransactionError as error:
    frappe.log_error(f"Transaction error: {error}")
```

---

## Class Constants

| Constant | Value | Description |
|---|---|---|
| `VARCHAR_LENGTH` | `255` | Default maximum length for variable-length string columns |
| `MAX_COLUMN_LENGTH` | `128` | SQL Server's maximum column name length |