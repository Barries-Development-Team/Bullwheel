# Adding a New Ascend Virtual DocType

This guide walks through creating a new read-only virtual DocType backed by an
Ascend RMS SQL Server table, using the Virtual DocType framework. Following it,
a new DocType needs only a `SCHEMA_CONFIG` dict and a tiny controller — no
hand-written SQL, filter logic, pagination, or sorting code.

> Reference implementation: `bullwheel/ascend/doctype/ascend_product/ascend_product.py`

---

## The Framework at a Glance

```
bullwheel/ascend/
├── virtual_doctype_base.py   AbstractVirtualDocType — inherit this
├── schema_config_builder.py  SCHEMA_CONFIG -> FIELD_TO_COLUMN / SELECT / SEARCH / JSON
├── schema_introspection.py   discover SQL Server columns + suggest a config
└── search_hook_helper.py     generate the Link-autocomplete search function
```

One `SCHEMA_CONFIG` dict on your controller is the single source of truth. The
base class derives everything else from it: the field→column map, the aliased
`SELECT` clause, the searchable columns, list ordering, and the search hook.

---

## Step 1 — Discover the table's columns

Run the introspection CLI against the Ascend database to see the real column
names and types. Use `--suggest` to also get a starter `SCHEMA_CONFIG`, and
`--primary-key` to include the required `"name"` entry in the output:

```bash
bench --site <your-site> introspect-schema --table Products --suggest --primary-key ID
```

`--server <SQL Server name>` targets a specific connection; omitted, it uses the
`default_database` from **Bullwheel Settings**. The output lists every column
with its SQL type, length, and nullability — write your config against these
verified names rather than guessing.

Without `--primary-key`, the suggested config will be missing the required `"name"`
entry and the command will print a reminder with an example to add it manually.

## Step 2 — Declare `SCHEMA_CONFIG`

Each entry maps a Frappe fieldname to its SQL mapping and UI intent. A `"name"`
entry is **required** — it declares the primary key SQL column and is what the
framework uses to populate Frappe's document identifier:

```python
SCHEMA_CONFIG = {
    "name":               {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
    "ascend_database_id": {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
    "description":        {"sql_column": "Description", "fieldtype": "Data", "display": "primary",   "searchable": True},
    "store_sku":          {"sql_column": "[Store UPC]", "fieldtype": "Data", "display": "secondary", "searchable": True},
    "category":           {"sql_column": None,          "fieldtype": "Data", "display": None,        "searchable": False},
    # ... one entry per field you want to surface
}
```

**The `"name"` entry** maps Frappe's internal document identifier directly to the
primary key SQL column. Because it appears in `SCHEMA_CONFIG`, it is projected in
the `SELECT` clause as `<column> AS name` and flows through like every other field —
no special-casing required. Its `sql_column` must not be `None`. You will typically
also declare a separate human-visible id field (e.g. `ascend_database_id`) pointing
to the same column so it appears on the form.

| Key          | Meaning |
|--------------|---------|
| `sql_column` | SQL Server column name. **Bracket-quote** names with spaces (`[Store UPC]`) or that collide with reserved words (`[Year]`). Use `None` for a field with no source column yet — it is projected as `NULL`. The `"name"` entry must have a non-null `sql_column`. |
| `fieldtype`  | Frappe fieldtype (`Data`, `Int`, `Currency`, `Check`, `Datetime`, …). |
| `display`    | List-view / autocomplete exposure: `"hidden"`, `"primary"`, `"secondary"`, or `None`. See below. |
| `searchable` | `True` to include the column in the OR LIKE Link autocomplete search. |

**`display` values**

- `"hidden"` — included in the document but never shown in the list view (use for `"name"` and UUID id fields).
- `"primary"` — the title / Link label; always shown. Use for the one main descriptive field.
- `"secondary"` — shown in lists and Link autocomplete alongside the primary.
- `None` — not shown in lists, but present in the full document form.

## Step 3 — Write the controller

Inherit `AbstractVirtualDocType` and declare two class attributes:

```python
# bullwheel/ascend/doctype/ascend_<thing>/ascend_<thing>.py
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class AscendThing(AbstractVirtualDocType):
    TABLE_NAME = "Things"   # Ascend SQL table name
    SCHEMA_CONFIG = { ... }  # from Step 2 — must include a "name" entry


# Link-field autocomplete hook (only if this DocType is a Link target)
ascend_thing_search = AscendThing.make_search_function(display_fields=["description"])
```

That's the whole controller. `load_from_db`, `get_list`, `get_count`, sorting,
and the read-only guards are all inherited. `make_search_function`'s
`display_fields` are the fieldnames shown after the id in each autocomplete row.

## Step 3b — Working with JOINs (optional)

When a field's value lives in a related table (e.g. resolving a category name from a
`Categories` table via a foreign key on `Products`), add a `JOIN_CONFIG` class
attribute alongside `SCHEMA_CONFIG`. Each list entry describes one SQL JOIN:

```python
JOIN_CONFIG = [
    {
        "join":  "LEFT JOIN",                          # JOIN type
        "table": "Categories",                         # Table to join
        "alias": "cat",                                # Optional alias
        "on":    "Products.TopicID = cat.ID",          # Full ON condition
    }
]
```

Renders as: `LEFT JOIN Categories AS cat ON Products.TopicID = cat.ID`

Multiple entries are concatenated in order, so you can chain as many JOINs as needed.

### Column qualification

With a JOIN in place, use dot notation (`table.column` or `alias.column`) in
`sql_column` whenever two tables share a column name — including the primary key.
The `"name"` entry should also be qualified in that case, since `load_from_db`
uses its `sql_column` directly in the `WHERE` clause:

```python
SCHEMA_CONFIG = {
    "name":               {"sql_column": "Products.ID",          "fieldtype": "Data", "display": "hidden",  "searchable": False},
    "ascend_database_id": {"sql_column": "Products.ID",          "fieldtype": "Data", "display": "hidden",  "searchable": False},
    "description":        {"sql_column": "Products.Description",  "fieldtype": "Data", "display": "primary", "searchable": True},
    "category":           {"sql_column": "cat.Topic",             "fieldtype": "Data", "display": None,      "searchable": False},
}
```

If the joined tables have no overlapping column names, qualification is optional
but still recommended for readability.

### Discovering joined-table columns

Use `--join-table` (repeatable) on the CLI to inspect the columns available from
each joined table before writing the config:

```bash
bench --site <site> introspect-schema --table Products --join-table Categories --suggest --primary-key ID
```

### Validating a JOIN config

Pass the joined-table columns as `additional_discovered_columns` to catch typos
in qualified `sql_column` references early:

```python
from bullwheel.ascend.virtual_doctype_base import get_default_ascend_database
from bullwheel.ascend.schema_introspection import introspect_table_schema, introspect_join_schemas
from bullwheel.ascend.schema_config_builder import validate_schema_config

server = get_default_ascend_database()
primary_schema  = introspect_table_schema(server, "Products")
joined_schema   = introspect_join_schemas(server, JOIN_CONFIG)

validate_schema_config(SCHEMA_CONFIG, primary_schema.keys(), joined_schema.keys())
```

Unqualified columns are validated against the primary table; qualified
`table.column` references are validated against the joined tables. Omitting
`additional_discovered_columns` skips validation for qualified columns.

---

## Step 4 — Create the DocType JSON

Create the DocType in the editor (`is_virtual = 1`), or scaffold its `fields`
array from your config:

```python
from bullwheel.ascend.schema_config_builder import build_json_schema
build_json_schema(SCHEMA_CONFIG)  # -> list of field dicts to drop into doctype.json
```

Set on the DocType:
- `is_virtual = 1`
- `autoname = field:ascend_database_id` (or whichever fieldname mirrors the primary key — not `field:name`, as that is a reserved meta-field and causes a naming loop)
- `title_field = <your "primary" display field>`
- The primary-key field marked `unique`; keep it out of `in_list_view` (it's a UUID).

The fieldnames in the JSON **must** match the keys in `SCHEMA_CONFIG`. The `"name"`
key in `SCHEMA_CONFIG` is handled by the framework and does not correspond to a
declared DocType field — omit it from the JSON.

## Step 5 — Register the search hook (Link targets only)

In `bullwheel/hooks.py`:

```python
standard_queries = {
    "Ascend Product": "bullwheel.ascend.doctype.ascend_product.ascend_product.ascend_product_search",
    "Ascend Thing":   "bullwheel.ascend.doctype.ascend_thing.ascend_thing.ascend_thing_search",
}
```

This bypasses Frappe's default search_widget pipeline, which is incompatible with
virtual DocType results.

## Step 6 — Migrate and verify

```bash
bench --site <your-site> migrate
```

Then check: the list view loads, **clicking a column header sorts** (the framework
wires `order_by` through automatically), filters work, and a Link field pointing
at the DocType autocompletes.

---

## Validating a config in code

`validate_schema_config` cross-checks your config against the live table so typos
surface early instead of as SQL errors:

```python
from bullwheel.ascend.virtual_doctype_base import get_default_ascend_database
from bullwheel.ascend.schema_introspection import introspect_table_schema
from bullwheel.ascend.schema_config_builder import validate_schema_config

schema = introspect_table_schema(get_default_ascend_database(), "Things")
validate_schema_config(SCHEMA_CONFIG, discovered_columns=schema.keys())
```

It raises `ValueError` if any `sql_column` doesn't exist in the table, a `display`
value is invalid, a required key is missing, or the `"name"` entry is absent or has
a null `sql_column`. Bracket-quoting is stripped before the column comparison.

---

## Gotchas & Known Limitations

**GUID / `uniqueidentifier` primary keys — handled automatically.** Many Ascend
tables key on a SQL Server `uniqueidentifier` (e.g. `Categories.ID`). pymssql
returns those columns as Python `uuid.UUID` objects, which Frappe cannot use as
identifiers (a UUID `name` or Link value raises `Unsupported filters type: UUID`
in the query builder). The base class normalizes every record through
`normalize_record`, converting UUID values to strings, so `name`, Link fields,
and filters all work. **No action needed** — just be aware the `name` will be the
lowercase, hyphenated GUID string.

**"Show Title in Link Fields" works on virtual DocTypes** — enable it normally
(set `show_title_field_in_link` and `title_field`). Frappe resolves link titles via
`frappe.db.get_value(doctype, name, title_field)` (and `get_values` for the version
diff), and core's query engine has **no virtual-doctype routing** — left alone it
runs the query against a `tab<DocType>` table that doesn't exist, raising
`Table '...' doesn't exist`. Bullwheel closes this gap in
`bullwheel/overrides/virtual_link_title.py`: it patches `Database.get_value` and
`Database.get_values` (installed once from `bullwheel/__init__.py`) so that, when the
DocType is virtual **and** the filters select rows purely by `name`, the value is
read through the controller's `load_from_db` instead of the database. All other calls
delegate to the original implementation untouched. This single choke point covers
every link-title path — form load, the `get_link_title` endpoint, version diffing,
print view — so a saved Link field shows the `title_field` (e.g. the product
description) rather than the raw GUID `name`.

## Why this shape

- **Single source of truth** — one `SCHEMA_CONFIG` drives the field map, SELECT
  clause, search columns, and JSON, so they cannot drift apart.
- **`name` is just another field** — declaring `"name"` in `SCHEMA_CONFIG` is
  explicit rather than inferred: the framework no longer needs to search for which
  field maps to the primary key, and the `WHERE` clause for `load_from_db` comes
  directly from `SCHEMA_CONFIG["name"]["sql_column"]`. No separate `PRIMARY_KEY_COLUMN`
  attribute is required.
- **Sorting fixed once** — `get_list` translates the list view's `order_by`
  (including DocType names with spaces) into a real SQL `ORDER BY`. No per-DocType
  sorting code, and no repeat of the original Ascend Product sorting bug.
- **UUIDs de-emphasized** — the `"hidden"` primary key stays out of list columns
  and is shown only as an id in autocomplete network responses, while remaining
  fully accessible on the form.
- **Explicit controllers** — the framework removes boilerplate but does not
  auto-generate controllers; you still see and own the class and its config.
