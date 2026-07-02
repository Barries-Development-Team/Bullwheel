# Virtual DocType Link-Title Patch

**Module:** `bullwheel/overrides/virtual_link_title.py`
**Applied from:** `bullwheel/__init__.py`
**Purpose:** Make Frappe's **"Show Title in Link Fields"** feature work for **virtual DocTypes**
(e.g. `Ascend Product`) whose data lives in an external SQL Server rather than a `tab<DocType>`
table.

---

## 1. Background — what "Show Title in Link Fields" does

A DocType can set two properties:

- `show_title_field_in_link = 1`
- `title_field = "<some fieldname>"` (e.g. `description`)

When enabled, anywhere a **Link field** points at that DocType, Frappe displays the linked
document's *title* (a human-friendly label) instead of its raw `name` (the primary key). For
`Ascend Product`, `name` is the Ascend GUID and `title_field` is `description`, so the UI shows the
product description instead of a meaningless GUID.

To do this, Frappe must translate a stored `name` into its title. On the **server** it resolves the
title with:

```python
frappe.db.get_value(doctype, docname, title_field)          # single value
frappe.db.get_values(doctype, {"name": ("in", names)}, [...]) # bulk (version diff)
```

Both of these ultimately live on the `Database` class
(`frappe.database.database.Database.get_value` / `get_values`).

---

## 2. The problem — virtual DocTypes have no table

`frappe.db.get_value` / `get_values` go **straight to the SQL query builder**, which builds a query
against a physical `tab<DocType>` table. A **virtual DocType** (`is_virtual = 1`) has **no such
table** — its data is served by its controller (`load_from_db`, `get_list`, …), which in Bullwheel
reads from an external SQL Server through `MSSQLDatabase`.

So every server-side title lookup for a virtual DocType runs a query against a table that does not
exist and raises:

```
ProgrammingError: Table 'yourdb.tabAscend Product' doesn't exist
```

This breaks **any** page that resolves a virtual link title. Critically, it breaks **form load** of
any document that links to a virtual DocType (e.g. a Warehouse Location whose child table links
`Ascend Product`).

### Where it breaks

Every affected code path bottoms out at the same two `Database` methods:

| Path | Frappe caller | Method used |
|------|---------------|-------------|
| **Form load** (the common crash) | `frappe.desk.form.load.get_title_values_for_link_and_dynamic_link_fields` (via `getdoc` → `set_link_titles`) | `get_value` |
| **On-demand Link fetch** | `frappe.desk.search.get_link_title` (whitelisted; JS `fetch_link_title`) | `get_value` |
| **Version diff on save** | `frappe.core.doctype.version.version` | `get_values` |
| Print view / Communication / Notification / Listview group-by | various | `get_value` |

---

## 3. The design decision — patch the single choke point

Only `get_link_title` is a *whitelisted* method (hookable via `override_whitelisted_methods`); the
rest are internal and not hookable. Rather than patch each path individually, Bullwheel patches the
**one shared choke point** both families of callers funnel through:

> `Database.get_value` and `Database.get_values`

Patching there fixes **every** path at once — including the whitelisted endpoint, so **no
`hooks.py` change is required**. All changes are contained in the Bullwheel app; Frappe core is not
modified.

The wrapper intercepts a call **only** when *both* are true:

1. the target DocType is **virtual**, and
2. the filters select rows **purely by `name`** (the exact shape every title path uses).

For everything else it **delegates to the original implementation untouched**, so behaviour for real
DocTypes — and for any exotic virtual query that isn't a name lookup — is unchanged.

---

## 4. How it is applied

`bullwheel/__init__.py`:

```python
from bullwheel.overrides.virtual_link_title import apply as _apply_virtual_link_title_patch
_apply_virtual_link_title_patch()
```

**Why here?** `frappe.get_hooks()` imports each installed app's `hooks` module very early in every
Frappe process (web request, background worker, scheduler). Importing `bullwheel.hooks` imports the
`bullwheel` package, which runs `bullwheel/__init__.py`. Therefore the patch is installed **before**
any whitelisted method or `getdoc` can run, in every process type.

`apply()` is **idempotent** — it sets a flag (`Database._bullwheel_virtual_link_title_patched`) and
returns early on subsequent calls, so repeated imports are harmless:

```python
def apply():
    if getattr(Database, _PATCHED_FLAG, False):
        return
    Database.get_value = _patched_get_value
    Database.get_values = _patched_get_values
    setattr(Database, _PATCHED_FLAG, True)
```

Because it rebinds methods **on the class**, every existing and future `frappe.db` instance uses the
wrapped versions. The originals are captured at import time (`_original_get_value`,
`_original_get_values`) so the wrappers can delegate to them.

---

## 5. How the patch works — component by component

### 5.1 The wrappers

Both wrappers share the same structure. `get_value` returns a single row; `get_values` returns a
list of rows.

```python
def _patched_get_value(self, doctype, filters=None, fieldname="name", *args, **kwargs):
    names = _names_from_filters(filters) if _is_virtual_link_doctype(doctype) else None
    if names is None:
        return _original_get_value(self, doctype, filters, fieldname, *args, **kwargs)
    ...
```

- The signature mirrors Frappe's: `(self, doctype, filters, fieldname, ...)`. Extra positional/keyword
  arguments are captured with `*args, **kwargs` and forwarded verbatim when delegating, so the wrapper
  stays compatible with Frappe's full parameter list.
- **Interception condition:** `_is_virtual_link_doctype(doctype)` is true **and**
  `_names_from_filters(filters)` returns a non-`None` list. If either fails, `names is None` and the
  call is delegated to the original.

### 5.2 The virtual check + re-entrancy guard — `_is_virtual_link_doctype`

Determining whether a DocType is virtual calls `is_virtual_doctype(doctype)`, which internally does
`frappe.get_meta(doctype)`. Loading meta issues **`frappe.db.get_value("DocType", ...)`** — i.e. it
**re-enters the very method we patched**. Without protection, that nested call would ask
"is `DocType` virtual?" again → load meta again → recurse forever.

The guard is a thread-local flag set only while the virtual check runs:

```python
_guard = threading.local()

def _is_virtual_link_doctype(doctype):
    if not isinstance(doctype, str) or getattr(_guard, "active", False):
        return False           # nested call during the check → let the original handle it
    _guard.active = True
    try:
        return is_virtual_doctype(doctype)
    finally:
        _guard.active = False
```

- While `active` is `True`, any nested `get_value`/`get_values` (from meta loading, controller import,
  etc.) sees the guard and returns `False` immediately, so it **delegates to the original** and hits
  the real `tabDocType` table normally.
- It is **thread-local** so concurrent requests never see each other's guard state.
- After the first successful check, `is_virtual_doctype` is `@site_cache`d, so subsequent checks are a
  cheap dict lookup with no DB round-trip.

### 5.3 Recognising a name-only lookup — `_names_from_filters`

The wrapper only intercepts lookups that select rows **by `name`** — that is the exact shape every
title path produces. `_names_from_filters` normalises the supported shapes into a **list of names**,
and returns `None` for anything else (signalling "not a title lookup — don't touch it"):

| Filter shape | Example | Result |
|---|---|---|
| bare name string | `"PROD-1"` | `["PROD-1"]` |
| dict, name equality | `{"name": "PROD-1"}` | `["PROD-1"]` |
| dict, name `in` | `{"name": ("in", ["PROD-1", "PROD-2"])}` | `["PROD-1", "PROD-2"]` |
| dict, explicit `=` | `{"name": ("=", "PROD-1")}` | `["PROD-1"]` |
| list, 3-element | `[["name", "=", "PROD-1"]]` | `["PROD-1"]` |
| list, 4-element (qualified) | `[["Ascend Product", "name", "in", [...]]]` | `[...]` |
| **anything else** | `{"description": "..."}`, `{"name": ("like", ...)}`, mixed keys | `None` (delegate) |

Two small helpers support it:

- `_parse_list_condition(condition)` — unpacks a list-format condition, accepting both
  `[fieldname, operator, value]` and the table-qualified `[doctype, fieldname, operator, value]`
  forms.
- `_names_from_operator_value(value)` — resolves the value side of a `name` filter. Supports only
  `=` and `in` (the operators the title paths use); returns `None` for unsupported operators such as
  `like`.

> **Design note:** returning `None` vs `[]` is deliberate. `[]` is a valid "no names requested"
> result; `None` means "this is not a name-only lookup, delegate to the original."

### 5.4 Resolving the values — `_read_fields`

Once we have a name and the requested field(s), `_read_fields` fetches them **through the
controller** instead of the database:

```python
def _read_fields(doctype, name, fieldnames):
    controller = get_controller(doctype)
    fast_fetch = getattr(controller, "get_link_field_values", None)
    if callable(fast_fetch):                       # optional optimized path
        values = fast_fetch(name, fieldnames)
        return None if values is None else [values.get(f) for f in fieldnames]

    try:                                           # default path
        document = frappe.get_cached_doc(doctype, name)
    except frappe.DoesNotExistError:
        frappe.clear_last_message()
        return None
    return [document.get(f) for f in fieldnames]
```

It returns the requested field values **in order**, or `None` if the record does not exist.

- **Default path** — `frappe.get_cached_doc(doctype, name)` runs the controller's `load_from_db`
  (which for Ascend doctypes queries SQL Server) and reads the requested fields off the loaded
  document. `get_cached_doc` also means repeated lookups of the same record within a request are
  served from cache — matching the `cache=True` intent of the title call sites.
- **Optional optimized path** — if the controller exposes a `get_link_field_values(name, fieldnames)`
  classmethod, it is used instead. See §6.
- `get_controller(doctype)` is imported from `frappe.model.base_document` (there is **no**
  `frappe.get_controller` in this Frappe version) and is cached after first import.

### 5.5 Return-shape parity

Frappe callers expect specific return shapes depending on the arguments. The wrappers reproduce them
exactly, so callers cannot tell a virtual result from a real one:

**`get_value` (single row):**

| Arguments | Returns |
|---|---|
| single string `fieldname` | scalar value (or `None`) |
| list `fieldname` | list row `[v1, v2, ...]` |
| `as_dict=True` | `frappe._dict({field: value, ...})` |
| `pluck=True` | first field's scalar |
| no matching record | `None` |

**`get_values` (multiple rows):**

| Arguments | Returns |
|---|---|
| default | list of row lists `[[...], [...]]` |
| `as_dict=True` | list of `frappe._dict` |
| `pluck=True` | list of first-field scalars |
| missing records | silently skipped |

> **`as_dict` / `pluck` are read from `kwargs` only.** Every real title call site passes these at
> their default or as keyword arguments — none pass them positionally — so reading them from `kwargs`
> is safe. A hypothetical positional `as_dict` on a virtual **name** lookup does not occur in
> practice; non-name-shaped virtual calls already delegate.

---

## 6. The optional optimization hook — `get_link_field_values`

The default `_read_fields` path loads the **whole** document to read one or two columns. For a form
with a handful of links that is negligible (and cached), but a list view rendering many *distinct*
linked records would trigger one full-row load each.

To avoid that, a virtual controller may expose an **optional** classmethod:

```python
@classmethod
def get_link_field_values(cls, name, fieldnames) -> dict | None:
    ...  # return {fieldname: value, ...} for the record, or None if absent
```

`_read_fields` prefers it when present. Bullwheel's framework base class,
`AbstractVirtualDocType` (`bullwheel/ascend/virtual_doctype_base.py`), provides a default
implementation, so **every** Ascend virtual DocType gets it automatically:

```python
@classmethod
def get_link_field_values(cls, name, fieldnames):
    field_to_column = cls.field_to_column()
    select_expressions = ", ".join(
        f"{field_to_column.get(f) or 'NULL'} AS {f}" for f in fieldnames
    )
    ...
    query = f"SELECT {select_expressions} FROM {cls.TABLE_NAME}{join} WHERE {name_column} = %s"
    with MSSQLDatabase(get_default_ascend_database()) as ascend:
        result = ascend.sql(query=query, values=(name,), as_dict=True)
    return normalize_record(result[0]) if result else None
```

It selects **only the requested columns** (aliased to their Frappe fieldnames), targets the primary
key, reuses the framework's existing `field_to_column()` / `join_clause()` plumbing, and runs the row
through `normalize_record` so GUID (`uuid.UUID`) values become strings. Fields with no SQL column
(NULL placeholders, or unknown names) come back as `None`.

Virtual DocTypes that do **not** subclass the framework simply fall back to the `get_cached_doc`
path — nothing is required of them.

---

## 7. End-to-end example: opening a form that links a product

1. User opens a **Warehouse Location** whose child table links an `Ascend Product`.
2. Frappe's `getdoc` runs `set_link_titles` →
   `get_title_values_for_link_and_dynamic_link_fields`, which calls
   `frappe.db.get_value("Ascend Product", "<guid>", "description")`.
3. That call is now `_patched_get_value`:
   - `_is_virtual_link_doctype("Ascend Product")` → `True` (guarded against recursion).
   - `_names_from_filters("<guid>")` → `["<guid>"]`.
   - `_read_fields` → controller's `get_link_field_values("<guid>", ["description"])` →
     `SELECT Description AS description FROM Products WHERE ID = %s` on SQL Server.
   - Returns the description string.
4. Frappe puts the title into the form-load response (`_link_titles`); the browser caches it in
   `frappe._link_titles` and the Link field shows the description instead of the GUID.

No "Table doesn't exist" error, and the Link field renders a friendly label.

---

## 8. Safety, edge cases, and interactions

- **No recursion.** The thread-local guard ensures the meta/controller lookups triggered *during* the
  virtual check delegate to the original `Database` methods. The value-resolution path
  (`get_cached_doc` / `get_link_field_values`) reads via `MSSQLDatabase`, and
  `get_default_ascend_database()` reads a **real** Single DocType (Bullwheel Settings), so it never
  loops back into a virtual lookup.
- **Real DocTypes are unaffected.** For a non-virtual DocType the only added cost is a single
  `is_virtual_doctype()` call, which is `@site_cache`d.
- **Non-title virtual queries are untouched.** A virtual `get_value` with a non-name filter (e.g.
  `{"description": "..."}`) returns `None` from `_names_from_filters` and delegates to the original.
- **Missing records** return `None` (single) or are skipped (bulk), mirroring Frappe's own behaviour.

---

## 9. Testing

- `bullwheel/overrides/test_virtual_link_title.py`
  - `_names_from_filters` across all supported and rejected shapes.
  - `get_value` / `get_values` **return-shape parity** (scalar, list row, `as_dict`, `pluck`, missing
    records) against a stubbed controller.
  - `_read_fields` prefers `get_link_field_values` when present and falls back to `get_cached_doc`
    otherwise.
  - Delegation: non-virtual and non-name-filter calls fall through to the original.
- `bullwheel/ascend/test_virtual_doctype_base.py`
  - `get_link_field_values` builds the correct column-limited SQL (including JOINs), targets the
    primary key, stringifies UUID names, and returns `None` on no match.

Run:

```bash
bench --site <site> set-config allow_tests true   # revert afterward
bench --site <site> run-tests --app bullwheel
```

Quick live check in `bench --site <site> console`:

```python
from frappe.database.database import Database
Database._bullwheel_virtual_link_title_patched                       # True
frappe.db.get_value("Ascend Product", "<id>", "description")         # title, no crash
frappe.db.get_value("User", "Administrator", "first_name")           # real DocType: unchanged
```

---

## 10. Maintenance notes

- **Frappe upgrades.** The patch mirrors the signatures of `Database.get_value` / `get_values` and
  forwards unknown arguments via `*args, **kwargs`. If a future Frappe changes those signatures (e.g.
  adds a positional parameter before `*`), re-verify the wrappers and the return-shape parity. The
  return contracts (scalar / row / `as_dict` / `pluck`) are the most likely thing to drift.
- **`get_controller` location.** It is imported from `frappe.model.base_document`. There is no
  top-level `frappe.get_controller` in this version — do not switch to that without checking.
- **Adding a new virtual DocType.** If it subclasses `AbstractVirtualDocType`, link titles work with
  zero extra code (both the default `get_cached_doc` path and the optimized
  `get_link_field_values` are inherited). Just set `show_title_field_in_link` and `title_field` on the
  DocType.
- **Scope.** This module solves *link-title resolution* only. It does not make arbitrary
  `frappe.db.get_value(virtual_doctype, {arbitrary filters})` queries work — those still delegate to
  the original and are unsupported for virtual DocTypes.
