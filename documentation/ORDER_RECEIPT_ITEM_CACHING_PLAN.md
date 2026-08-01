# Order Receipt Item description/upc: back to computed fields, backed by a short-TTL cache

**Date:** 2026-07-31
**Scope:** `bullwheel/ascend/virtual_doctype_base.py`, `bullwheel/ascend/doctype/order_receipt_item/`, `bullwheel/ascend/doctype/order_receipt/`
**Status:** Approved implementation plan, not yet implemented.

## Context

`Order Receipt Item.description`/`upc` were originally `is_virtual` fields computed live from
`VendorProduct` (the Ascend-backed virtual doctype). That caused a real performance problem:
Frappe re-serializes every row of a child table on every table operation, so N rows meant N
fresh SQL Server connections (no pooling) on every add/edit/remove — not just the touched row.
The fix at the time was to make `description`/`upc` stored columns, filled once via a "snapshot"
(`populate_item_snapshot` in `order_receipt.py`) when a row is added/edited.

That traded the connection-storm problem for a staleness problem with no fix path: once
snapshotted, a row's `description`/`upc` never update again, even if Ascend's data changes later
(the same shape of bug as the `cached_vendor_id` issue already removed elsewhere in this app,
`CACHING_ANALYSIS.md` finding B4 — this is its unaddressed sibling, B5).

Now that the framework has Redis-backed caching (`cache_fields()`/`get_cached_value`), the goal
is to go back to computed fields — but sourced through a **short-TTL** cache tier (distinct from
the existing indefinite `cache_fields()` mechanism, which is only for genuinely-immutable
fields), plus a **batch fetch** so a cold cache across many rows costs one Ascend query, not N.
That combination is what makes going back to computed fields safe this time: a Redis `GET` is
cheap even N-per-load, and the one dangerous case — cold cache, N rows, N live queries in one
request — is closed by warming the whole child table in one query before the rows render.

Decisions already settled with the user (do not revisit):
1. **Freshness: refresh whenever viewed**, not just when a row is touched — e.g. an Ascend
   correction should show up next time the receipt is opened.
2. **No special-casing `received` rows** — one freshness policy for every row, finalized or not.

## Design

### 1. Two new primitives on `AbstractVirtualDocType` (`bullwheel/ascend/virtual_doctype_base.py`)

**`get_values_many(cls, names: list, fields: list) -> dict`** — placed after `get_values`
(~line 456). Batch version of `get_values`, via a local SQL Server temp table joined against
`TABLE_NAME`, not a `WHERE name IN (...)` clause:

```python
with MSSQLDatabase(get_default_ascend_database()) as db:
    db.sql("CREATE TABLE #lookup_names (lookup_name NVARCHAR(MAX) NOT NULL)", as_dict=False)

    for start in range(0, len(unique_names), cls.MAX_BATCH_INSERT_SIZE):
        chunk = unique_names[start:start + cls.MAX_BATCH_INSERT_SIZE]
        placeholders = ', '.join(['(%s)'] * len(chunk))
        db.sql(f"INSERT INTO #lookup_names (lookup_name) VALUES {placeholders}", values=chunk, as_dict=False)

    query_clauses = [select_clause, f'FROM {cls.TABLE_NAME}']
    if cls.JOIN_CONFIG is not None:
        query_clauses.append(cls._build_join_clause())
    query_clauses.append(f'INNER JOIN #lookup_names ON {name_column} = #lookup_names.lookup_name')
    records = db.sql(query=' '.join(query_clauses), as_dict=True)
```

Two reasons this beats `WHERE ... IN (...)`, and why it does **not** route through
`_build_where_clause`'s `'in'` operator:

- **Confirmed bug in the existing `'in'` path**: `_format_condition` (line 286) does
  `values.append(value)` for a filter value that would be a *list*, producing exactly one `%s`
  placeholder bound to a nested list rather than one placeholder per element — this does not
  render correct SQL against pymssql, and nothing in the codebase currently exercises it
  successfully (`bullwheel/patches/backfill_order_item_snapshot.py` calls
  `frappe.get_all("Vendor Product", filters={"name": ["in", chunk]})`, a live example of code
  that would hit this exact path — informational only, that patch is already recorded and won't
  re-run).
- **A temp table sidesteps SQL Server's query-parameter cap entirely.** An `IN (...)` clause
  needs one bound parameter per name, competing against SQL Server's ~2100-parameters-per-query
  limit alongside the SELECT/JOIN's own parameters. A temp table's constraint is instead T-SQL's
  documented 1000-rows-per-multi-row-`INSERT...VALUES` limit — independent of the lookup query's
  own parameter count, and far higher than any realistic caller here (an Order Receipt's item
  count). `MAX_BATCH_INSERT_SIZE = 1000` chunks the INSERT only, matching that limit.
- **Permissions**: local (`#`-prefixed) temp tables live in `tempdb`, which grants `CREATE TABLE`
  to the `public` role by default — every login that can connect to the instance gets this for
  free, no elevated grant needed beyond whatever Bullwheel's login already has for its normal
  SELECT/INSERT work. Confirmed `MSSQLDatabase` reuses one connection across multiple `.sql()`
  calls inside a `with` block (`SQLServer.py:120` — each call opens a new *cursor*, not a new
  connection), so `CREATE TABLE`/`INSERT`/`SELECT` all share one session and see the same temp
  table; it's auto-dropped when the block's connection closes, no explicit `DROP TABLE` needed.

Filters/joins on `_column_for('name')` (handles `NAME_EXPRESSION`-as-computed-SQL correctly,
e.g. `VendorProduct`'s `CONCAT(PartNumber, ' (', Vendor.Name, ')')` — not necessarily a raw
column; the join predicate is an equality match against that expression, same cost profile an
IN clause would have paid against it). Selects with
`_build_select_clause(list(dict.fromkeys(['name', *fields])), strict=True)` (note:
`_build_select_clause` only auto-adds `'name'` when the field list is empty, so it must be
prepended explicitly here). Returns `{name: frappe._dict({field: value, ...})}`; a name with no
Ascend match is simply absent — mirrors `get_values`' single-record contract.

**`get_short_cached_values_many(cls, names: list, fields: list, ttl: int = None) -> dict`** —
placed after `get_cached_value` (~line 471). For fields that genuinely can change in Ascend
(no `cache_fields()` gate — any SCHEMA_CONFIG-mapped field is eligible): checks Redis for every
`(name, field)` pair across all `names` in one pass, collects the names with at least one
miss, fetches every requested field for the whole miss set with **one** `get_values_many` call,
repopulates Redis for each resolved value with `expires_in_sec=ttl`, returns
`{name: frappe._dict({field: value, ...})}`. A name with no cache hit and no Ascend match is
absent from the result (negative lookups are never cached, matching this app's existing policy
against caching "not found").

This single method covers both call sites below — a single name is just a list of length one,
so no separate single-name variant is needed.

Add `MAX_BATCH_INSERT_SIZE: int = 1000` and `SHORT_CACHE_TTL_SECONDS: int = 300` (5 min) to the
"Subclass Contract" block, `SHORT_CACHE_TTL_SECONDS` overridable per controller. Default value is
empirically motivated, not a fixed constraint — 5 minutes is short enough that an Ascend
correction shows up on the next view in the common case (bounded at 5 min worst case), long
enough that an active receiving session (reloading the same receipt repeatedly over a few
minutes) serves almost every reload from Redis.

**Redis correctness detail** — confirmed against `frappe/utils/redis_wrapper.py`:
`set_value(key, val, expires_in_sec=...)` is correct (already used identically in
`bullwheel_core/__init__.py:21`). But **reads must pass `expires=True`** to
`frappe.cache.get_value(key, expires=True)`: the default `expires=False` path additionally
caches the value in `frappe.local.cache` (a per-process dict) with no TTL awareness, which is
correct for `get_cached_value`'s indefinite cache but would undermine a short-TTL entry within
a single long-lived request. `get_cached_value`'s existing call (line 466) doesn't need this —
don't copy it verbatim into the new method.

### 2. `order_receipt_item.py` / `.json`

Convert `description`/`upc` back to `is_virtual`, computed via `@property`, memoized per
document instance — mirroring `location_inventory.py`'s `_ascend_fields()` pattern exactly
(the better reference of the two existing examples, since `location_inventory.json` is also a
real child table, `istable: 1`, confirming `is_virtual` on a child DocType already works in this
app — not a novel risk):

```python
from bullwheel.ascend.doctype.vendor_product.vendor_product import VendorProduct

class OrderReceiptItem(Document):
    LABEL_RESOLUTION_FIELD = 'vpn'

    def _ascend_fields(self):
        if not hasattr(self, "_ascend_field_cache"):
            self._ascend_field_cache = (
                VendorProduct.get_short_cached_values_many([self.vpn], ["description", "upc"]).get(self.vpn)
                if self.vpn else None
            )
        return self._ascend_field_cache

    @property
    def description(self):
        fields = self._ascend_fields()
        return fields.get("description") if fields else None

    @property
    def upc(self):
        fields = self._ascend_fields()
        return fields.get("upc") if fields else None
```

`order_receipt_item.json`: add `"is_virtual": 1` to both `description` and `upc` fields; remove
`"in_standard_filter": 1` from `description` (Frappe's list/report SQL builder has no per-field
`is_virtual` awareness — a standard filter on it would query the now-dropped column). Keep
`in_list_view`, `label`, `read_only`.

`order_receipt.js`'s `is_editable_field` and `order_receipt.py`'s `writable_fieldnames()` already
exclude `is_virtual` fields — the Add/Edit Item dialogs automatically stop offering
description/upc as inputs once this lands; no separate change needed there, but it's what makes
the parameter cleanup below safe.

### 3. `order_receipt.py` / `.js`

Add `OrderReceipt.onload()` — batch-warms the cache for every row's vpn in one query before
Frappe serializes the child table:

```python
def onload(self):
    vpns = [item.vpn for item in self.order_items if item.vpn]
    if vpns:
        VendorProduct.get_short_cached_values_many(vpns, ["description", "upc"])
```

Note on mechanism (confirmed against `frappe/desk/form/load.py` vs `frappe/model/document.py`):
`onload()` only fires via `frappe.desk.form.load.getdoc` (the Desk form-load endpoint) — **not**
inside a plain `frappe.get_doc()` call, so it does not run inside `update_table`'s or
`add_or_increment_item`'s enqueued jobs directly. It still covers the case that matters: those
jobs' `doc.save()` fires a `doc_update` realtime event, the client's non-dirty-form listener
reloads the form, and that reload goes through `getdoc` → `onload()`. Paths that load the
document without going through Desk (REST API, print formats, `export_received_batch`, label
printing) don't get the proactive batch-warm and fall back to a per-row cache-or-query — same
cost as today's snapshot-at-add-time model in the worst case, never worse.

Remove `populate_item_snapshot` entirely and its call site in `update_table` (the
`row.description = row.upc = None; populate_item_snapshot(row)` block). Drop the now-dead
`description`/`upc` parameters from `add_or_increment_item`, `queue_add_or_increment_item`, and
their callers in `order_receipt.js` (the scan-flow call and `open_new_product_form_dialog`'s
`after_insert`). **Do not** touch `link_vendor_product`'s `description` parameter — that one is
real, forwarded to `create_vendor_product`, which writes `VendorProducts.Description` in Ascend
on insert; only drop its `upc` parameter. Reason this cleanup is necessary, not just tidy: once
`description`/`upc` are properties with no setter, `doc.append(table, {"description": ...})`
writes into `self.__dict__` directly (per `base_document.py`, bypassing `__set__`) — the value is
never read again, so leaving these parameters in place would be silently dead code that looks
load-bearing.

`scan_item`'s own inline SQL Server query stays untouched — that's live UI feedback for an
unsaved scan-dialog, unrelated to row storage.

### 4. Migration

New patch, `bullwheel/patches/drop_order_item_snapshot_columns.py`, registered in
`patches.txt`'s `[post_model_sync]` after `backfill_order_item_snapshot`:

```python
import frappe

def execute():
    for column in ("description", "upc"):
        if frappe.db.has_column("Order Receipt Item", column):
            frappe.db.sql_ddl(f"ALTER TABLE `tabOrder Receipt Item` DROP COLUMN `{column}`")
```

Drop rather than leave orphaned (reversing this app's usual "Frappe never drops removed columns,
leave them" precedent, for a concrete reason): Frappe's list/report query builder
(`frappe/model/db_query.py`) only special-cases `is_virtual` at the whole-DocType level, never
per field. A future `frappe.get_all("Order Receipt Item", fields=["description", "upc"])` —
exactly the pattern `backfill_order_item_snapshot.py` already uses elsewhere in this app — would,
if the columns still existed, silently return the frozen pre-migration snapshot instead of
computing the live value or erroring, directly violating decision #1 with no visible symptom.
Dropping the columns turns that into a loud, immediate SQL error instead.

## Verification

- New unit tests in `test_virtual_doctype_base.py`: `get_values_many` — temp table created and
  populated with one row per name (flattened `values` on the `INSERT`, chunked at
  `MAX_BATCH_INSERT_SIZE`), the final `SELECT` joins on `_column_for('name')` (not necessarily a
  raw column — regression-test against a `NAME_EXPRESSION`-shaped fixture), dict keyed by name,
  missing name absent. `get_short_cached_values_many` — cold cache issues exactly
  one `MSSQLDatabase` call and one `set_value(..., expires_in_sec=...)` per resolved field; warm
  cache issues zero DB calls; mixed hot/cold across several names batches only the misses; a
  name with no Ascend match is absent and never cached. Mock `frappe.cache.get_value`/
  `set_value` alongside the existing `MSSQLDatabase` mock pattern already used in this file.
- `bench --site <site> migrate` on a site with existing Order Receipt data: confirm the new patch
  runs and `SHOW COLUMNS FROM \`tabOrder Receipt Item\`` no longer lists `description`/`upc`.
- Manual, via `bench --site <site> console`: `VendorProduct.get_short_cached_values_many([vpn], ["description","upc"])`, confirm `frappe.cache.get_value(f'{VendorProduct.TABLE_NAME}-{vpn}-description-ttl', expires=True)` round-trips and actually expires (`redis-cli TTL <key>`).
- Manual, via Desk: open a receipt with several items, confirm Description/Barcode render
  correctly and instantly on a same-window reload (warm path); edit the underlying Ascend value
  directly (or expire/delete the Redis key), reload, confirm the new value appears — this is the
  concrete proof of "refresh whenever viewed." Confirm the Add/Edit Item dialog no longer offers
  Description/Barcode as inputs.
- `bench --site <site> run-tests --app bullwheel` — full suite should still pass.

## Critical files

- `bullwheel/ascend/virtual_doctype_base.py` — `get_values_many`, `get_short_cached_values_many`, `SHORT_CACHE_TTL_SECONDS`, `MAX_BATCH_INSERT_SIZE`
- `bullwheel/ascend/doctype/order_receipt_item/order_receipt_item.py` and `.json`
- `bullwheel/ascend/doctype/order_receipt/order_receipt.py` and `.js`
- `bullwheel/ascend/test_virtual_doctype_base.py`
- `bullwheel/patches/drop_order_item_snapshot_columns.py` (new) and `bullwheel/patches.txt`
