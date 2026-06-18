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
names and types. Use `--suggest` to also get a starter `SCHEMA_CONFIG`:

```bash
bench --site <your-site> introspect-schema --table Products --suggest
```

`--server <SQL Server name>` targets a specific connection; omitted, it uses the
`default_database` from **Bullwheel Settings**. The output lists every column
with its SQL type, length, and nullability — write your config against these
verified names rather than guessing.

## Step 2 — Declare `SCHEMA_CONFIG`

Each entry maps a Frappe fieldname to its SQL mapping and UI intent:

```python
SCHEMA_CONFIG = {
    "ascend_database_id": {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
    "description":        {"sql_column": "Description", "fieldtype": "Data", "display": "primary",   "searchable": True},
    "store_sku":         {"sql_column": "[Store UPC]", "fieldtype": "Data", "display": "secondary", "searchable": True},
    "category":          {"sql_column": None,          "fieldtype": "Data", "display": None,        "searchable": False},
    # ... one entry per field you want to surface
}
```

| Key          | Meaning |
|--------------|---------|
| `sql_column` | SQL Server column name. **Bracket-quote** names with spaces (`[Store UPC]`) or that collide with reserved words (`[Year]`). Use `None` for a field with no source column yet — it is projected as `NULL`. |
| `fieldtype`  | Frappe fieldtype (`Data`, `Int`, `Currency`, `Check`, `Datetime`, …). |
| `display`    | List-view / autocomplete exposure: `"hidden"`, `"primary"`, `"secondary"`, or `None`. See below. |
| `searchable` | `True` to include the column in the OR LIKE Link autocomplete search. |

**`display` values**

- `"hidden"` — included in the document but never shown in the list view (use for the UUID primary key).
- `"primary"` — the title / Link label; always shown. Use for the one main descriptive field.
- `"secondary"` — shown in lists and Link autocomplete alongside the primary.
- `None` — not shown in lists, but present in the full document form.

Exactly one field must map its `sql_column` to the table's primary key column
(see `PRIMARY_KEY_COLUMN` in the next step) — that field becomes Frappe's `name`.

## Step 3 — Write the controller

Inherit `AbstractVirtualDocType` and declare three class attributes:

```python
# bullwheel/ascend/doctype/ascend_<thing>/ascend_<thing>.py
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class AscendThing(AbstractVirtualDocType):
    TABLE_NAME = "Things"        # Ascend SQL table name
    PRIMARY_KEY_COLUMN = "ID"    # SQL primary key column
    SCHEMA_CONFIG = { ... }       # from Step 2


# Link-field autocomplete hook (only if this DocType is a Link target)
ascend_thing_search = AscendThing.make_search_function(display_fields=["description"])
```

That's the whole controller. `load_from_db`, `get_list`, `get_count`, sorting,
and the read-only guards are all inherited. `make_search_function`'s
`display_fields` are the fieldnames shown after the id in each autocomplete row.

## Step 4 — Create the DocType JSON

Create the DocType in the editor (`is_virtual = 1`), or scaffold its `fields`
array from your config:

```python
from bullwheel.ascend.schema_config_builder import build_json_schema
build_json_schema(SCHEMA_CONFIG)  # -> list of field dicts to drop into doctype.json
```

Set on the DocType:
- `is_virtual = 1`
- `autoname = field:<your primary-key fieldname>` (e.g. `field:ascend_database_id`)
- `title_field = <your "primary" display field>`
- The primary-key field marked `unique`; keep it out of `in_list_view` (it's a UUID).

The fieldnames in the JSON **must** match the keys in `SCHEMA_CONFIG`.

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
validate_schema_config(SCHEMA_CONFIG, "ID", discovered_columns=schema.keys())
```

It raises `ValueError` if any `sql_column` doesn't exist in the table, a `display`
value is invalid, a required key is missing, or the primary key isn't mapped by
exactly one field. Bracket-quoting is stripped before the column comparison.

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

**Do NOT enable "Show Title in Link Fields" on a virtual DocType.** That setting
makes Frappe resolve link titles via `frappe.db.get_value(doctype, name, title_field)`,
and core's query engine has **no virtual-doctype routing** — it runs the query
against a `tab<DocType>` table that doesn't exist for virtual DocTypes, raising
`Table '...' doesn't exist`. Leave the setting off (it is off by default). The
framework's `display` config already gives Link autocomplete a friendly label, so
users still see a description rather than a raw GUID when picking a value. (If a
saved Link field shows the raw GUID name in the form, that is the cost of this
core limitation, not a framework bug.)

## Why this shape

- **Single source of truth** — one `SCHEMA_CONFIG` drives the field map, SELECT
  clause, search columns, and JSON, so they cannot drift apart.
- **Sorting fixed once** — `get_list` translates the list view's `order_by`
  (including DocType names with spaces) into a real SQL `ORDER BY`. No per-DocType
  sorting code, and no repeat of the original Ascend Product sorting bug.
- **UUIDs de-emphasized** — the `"hidden"` primary key stays out of list columns
  and is shown only as an id in autocomplete network responses, while remaining
  fully accessible on the form.
- **Explicit controllers** — the framework removes boilerplate but does not
  auto-generate controllers; you still see and own the class and its config.
