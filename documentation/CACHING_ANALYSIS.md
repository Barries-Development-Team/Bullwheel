# Caching Analysis — Virtual DocType Framework & Order Receipt

**Date:** 2026-07-30
**Scope:** `bullwheel/ascend/virtual_doctype_base.py`, the virtual DocType controllers, the
Order Receipt receiving flow, and everything they call into (`MSSQLDatabase`,
`bullwheel_core`, `label_printing`, the `virtual_link_title` monkey patch).
**Deliverable:** analysis only — no code was changed by this report.

---

## Cache Implementations

- [x] `get_default_ascend_database()`
  - Average before caching: 4.25 ms
  - Average after caching: 1.19 ms
- [ ] ~~`MSSQLDatabase.__init__` Password Decryption~~ Not viable.
  - get_decrypted_password loads the source document via query. Consider just decrypting the encrypted value passed to __init__.
  - Average before cahcing: 4.63 ms

## 0. Executive summary

Every read of Ascend data in Bullwheel is a fresh round trip: a MariaDB lookup for the
`SQL Server` credentials, a `get_decrypted_password` call, a TCP connect/TLS handshake to
SQL Server, one query, then a disconnect. Nothing at any layer is reused between calls.
The framework already *declares* cacheability (`SCHEMA_CONFIG`'s `cache` flag,
`cache_fields()`) but nothing consumes it, and `MSSQLDatabase.value_cache` is allocated,
cleared on commit/rollback, and never read or written.

The highest-value work, in order:

| # | Target | Why it's the top of the list |
|---|---|---|
| 1 | `get_default_ascend_database()` + `MSSQLDatabase.__init__` | Runs on **every** Ascend query. Two MariaDB round trips + a decrypt, per query, per connection. Pure overhead — the payload isn't even Ascend data. |
| 2 | Static/reference lookups (`Vendor.id`, `Product Category`, category autocompletes) | Low-cardinality, effectively immutable, queried constantly by Link fields. |
| 3 | Label-print resolution chains (`resolve_to_native`) | N SQL Server queries per printed item, ×2 hops for order items. Worst N+1 in the app. |
| 4 | Mirrored-field reads (`Location Inventory`, `Ski with Bindings`) | One SQL Server query per child row; the existing memo only covers a single row. |
| 5 | `get_count` on `Ascend Product` | `COUNT(*)` over ~200k rows with two JOINs, on every list-view page load. |

**The constraint that shapes every recommendation:** Ascend RMS writes its own database
outside Bullwheel. There is no change feed, no trigger, no event. Any cached Ascend value
can go stale silently. So caching must be limited to (a) values declared `cache`,
(b) short TTLs where a few seconds of staleness is harmless, and (c) values Bullwheel
itself owns the writes for, invalidated at the framework's own write choke points
(`db_insert`/`db_update`/`create_vendor_product`).

---

## Part A — Areas that would benefit from Frappe Redis caching

### A1. `get_default_ascend_database()` — the per-query tax  ⭐ highest value

`bullwheel/bullwheel_core/__init__.py:13`

```python
def get_default_ascend_database():
    default_database = frappe.db.get_single_value('Bullwheel Settings', 'default_database')
    return frappe.get_doc("SQL Server", default_database)
```

**Call sites (every one of them per-query, not per-request):**
`virtual_doctype_base.py` — `load_from_db` (406), `get_values` (439), `get_list` (522),
`get_count` (563), `db_insert` (734), `db_update` (769); `order_receipt.py:235`
(`scan_item`); `vendor_product.py` — `vendor_product_match_count` (82), `generate_vpn`
(124), `create_vendor_product` (141); `schema_introspection.py`.

**What each call costs:**

1. `frappe.db.get_single_value` — cheap after the first hit in a request (frappe.db keeps a
   per-request `value_cache` for Singles), but it is a fresh query in every background job,
   and the receiving flow runs almost entirely in enqueued jobs.
2. `frappe.get_doc("SQL Server", …)` — **uncached**. A full document load from MariaDB on
   every single Ascend query.
3. `MSSQLDatabase.__init__` (`SQLServer.py:34`) then calls `get_decrypted_password(...)`,
   which queries the `__Auth` table and runs an AES decrypt — again, per query.

A single Order Receipt list view or a scan can trigger this chain a dozen times.
`generate_vpn`'s counter loop constructs it once but hammers the same connection — good —
while `_generate_store_sku` calls `AscendProduct._record_exists` up to 20 times, each one a
full credentials fetch + new connection.

**Recommendation**

- Swap `frappe.get_doc("SQL Server", …)` → `frappe.get_cached_doc("SQL Server", …)`. This is
  a one-line change, Redis-backed, and correctly invalidated by Frappe when the `SQL Server`
  doc is saved.
- Replace the Single read with `frappe.get_cached_value("Bullwheel Settings", "Bullwheel
  Settings", "default_database")` (or `frappe.get_cached_doc`) so it is Redis-backed rather
  than per-request.
- **Do not put the decrypted password in Redis.** Frappe's Redis is typically
  unauthenticated on the bench host, and this is a live SQL Server credential. Memoize it
  per-request instead (`frappe.utils.caching.request_cache`, or a `frappe.local` attribute),
  which already collapses the dozen-per-request case to one without writing a secret to a
  shared store.
- Bigger win, more work: pool/reuse one `MSSQLDatabase` per request instead of opening and
  closing a connection per query. That is a connection-lifecycle change, not a cache, but it
  removes the same overhead this section is about and is worth costing out alongside.

### A2. `Vendor.get_values(vendor, ['id'])` — static value, re-queried

`order_receipt.py:21` (`OrderReceipt.validate`) and `new_product.py:187`
(`NewProduct._resolve_vendor_id`).

`Vendor.SCHEMA_CONFIG['id']` is already declared `{'column': 'ID', 'cache': True}` — an
Ascend identity column that never changes for a given vendor. Barrie's has on the order of
hundreds of vendors, keyed by a name that is itself the Frappe docname.

This is exactly what a long-TTL (hours) `frappe.cache` hash keyed on the vendor name is for:

```python
# illustrative
vendor_id = frappe.cache.hget("bullwheel:ascend_vendor_id", vendor_name,
                              generator=lambda: Vendor.get_values(vendor_name, ["id"]).id)
```

Note that Order Receipt currently solves this with a persisted field instead — see **B4**,
which is also a correctness bug.

### A3. `Product Category` — a small, near-static table behind a Link field

`ProductCategory` maps `Categories` (a few hundred rows, changed rarely, and only from
inside Ascend). It is reached from:

- the `category` Link on `Ascend Product` / `New Product` — one `get_list` **per keystroke**
  of autocomplete, plus a `get_count`;
- `_resolve_linked_id_fields` (`virtual_doctype_base.py:686-697`), which runs a `get_count`
  *and* a `get_values` against `Product Category` on every Ascend Product save where the
  category changed — two more SQL Server round trips inside the save path.

Caching the whole `Categories` projection under one Redis key with a medium TTL (say 15–60
minutes), and serving both the link search and the linked-id resolution from it, removes
essentially all of this traffic. The linked-id resolution in particular is on the critical
path of a user-visible save.

### A4. `get_list` / `get_count` on the virtual base class

`virtual_doctype_base.py:487` and `:550`.

- **`get_count`** is the stronger candidate. Frappe's list view calls it for pagination on
  every page load, and for `Ascend Product` it is `SELECT COUNT(*)` over ~200k rows joined
  to `Categories` and `Users`. The result is a single integer and, for a warehouse UI, being
  30–60 seconds stale is invisible. Cache keyed on a hash of `(doctype, filters, or_filters)`
  with a short TTL.
- **`get_list`** is more nuanced. Link-field searches (`Ascend Product` autocomplete during
  receiving) repeat the same few prefixes constantly and would cache well at a 30–60s TTL;
  full list views with arbitrary filter/sort/pagination combinations have poor hit rates and
  a large per-entry payload. If this is pursued, scope it to the link-search shape
  (`as_list=True` with a `_relevance` field, small `page_length`) rather than all of
  `get_list`.
- Both need a stable cache key. `_build_where_clause` already produces a canonical SQL
  string plus a bound-values list — hashing `(select_clause, where_clause, values, order_by,
  start, page_length)` is a natural key, and the framework is the single choke point where it
  can be computed.
- Invalidation: `db_insert`/`db_update` on the same controller should drop that DocType's
  namespace (`frappe.cache.delete_key("bullwheel:ascend_list:Ascend Product")`), so
  Bullwheel's own writes are never served stale from its own cache. Ascend-side writes still
  ride the TTL out.

### A5. Mirrored virtual fields — `Location Inventory` and `Ski with Bindings`

`location_inventory.py:12-21`, `ski_with_bindings.py:10-19`.

Both memoize `AscendProduct.get_values(...)` on the **document instance**. That collapses
several properties on one row into one query, but a Warehouse Location holding 40 SKUs still
issues 40 SQL Server round trips (each with its own connect and its own credential fetch —
see A1) to render its child grid.

`description`, `upc`, `brand`, `style_name`, `size`, `gender`, `year` for a given product are
near-immutable in practice, and `name`/`id` are declared `cache`. A Redis cache keyed
`(doctype, name)` holding the mirrored field dict, with a TTL of minutes, turns the grid
render into one Ascend query for cold rows and zero for warm ones.

This is also the natural first consumer of `cache_fields()` (`virtual_doctype_base.py:146`),
which currently exists purely as a declaration with the docstring "Nothing consumes this yet
— it is declared so a future caching layer has the information it needs."

### A6. Label-print resolution — the worst N+1 in the receiving flow

`label_printing/resolution.py:186` (`resolve_to_native`) and `label_printing/__init__.py:116`.

Printing tags for selected order items walks, **per item**:

`Order Receipt Item` → `vpn` → `Vendor Product` (SQL Server query via the monkey patch) →
`product` → `Ascend Product` (second SQL Server query), then `frappe.get_doc` on the native
document to render the label (a third).

Selecting 40 order items and hitting "Print Ascend Tag" is therefore ~80–120 SQL Server
round trips, each preceded by its own credentials fetch. The existing `document_cache` dict
(`__init__.py:116`) only dedupes *within* one print call.

Two complementary fixes:

1. Cache the resolution hop itself — `(doctype, name) → (native_doctype, native_name)` is a
   foreign-key relationship that effectively never changes. Long TTL, high hit rate.
2. Give `VendorProduct` and `AscendProduct` the `get_link_field_values(name, fieldnames)`
   fast-path classmethod the monkey patch already looks for
   (`virtual_link_title.py:154`, documented in `MONKEY_PATCH.md` § 1.6), backed by the A5
   cache. Today neither controller defines it, so every hop takes the
   `get_cached_doc` fallback and loads the entire row to read one column.

### A7. `frappe.db.get_single_value('Bullwheel Settings', …)` call sites

`get_default_ascend_database` (A1), `get_label` (`bullwheel_core/__init__.py:23`),
`ski_category_prefix` (`:35`, wired to `extend_bootinfo` — **runs on every desk page load,
for every user**), `NewProduct._is_ski_hardgood` (`new_product.py:196`).

Singles are cheap, but `frappe.get_cached_value("Bullwheel Settings", "Bullwheel Settings",
field)` is Redis-backed and correctly invalidated on save, versus a per-request-only cache.
The bootinfo hook is the one that actually matters at scale.

Likewise `get_label` → `frappe.get_doc("Zebra Printer Label", …)` and `print_labels` →
`frappe.get_doc("Label Printer", …)` (`label_printing/__init__.py:33, 91`) are read-only
config documents that should be `frappe.get_cached_doc`.

### A8. `AscendProduct.swap_price` / `online_price`

`ascend_product.py:110-116` — two `frappe.db.get_value('Product Price', …)` calls per
document load. MariaDB, so cheap, but they are unbatched and fire on every form load and
every label render. `frappe.get_cached_value` would serve them from Redis with correct
invalidation, since Bullwheel owns all writes to `Product Price`.

### A9. Schema introspection / migrate-time validation

`schema_introspection.py` queries `INFORMATION_SCHEMA.COLUMNS`, and
`validate_virtual_doctypes.py` runs (via `before_migrate`) with optional live column checks
— one introspection query per controller. Low frequency, so low priority, but if live
validation is ever enabled by default, caching the per-table column list for the duration of
the migrate (a `request_cache`, not Redis) avoids re-querying the same table for every
controller that references it.

### A10. Explicitly **do not** cache

These look cacheable and are not:

- **`AbstractVirtualDocType._record_exists`** (`:576`) and
  `_part_number_match_count` (`vendor_product.py:58`) — uniqueness guards. A cached negative
  result lets `db_insert` create a duplicate row in Ascend, and a cached positive result
  makes `_generate_store_sku` spin through all 20 attempts. Correctness depends on these
  being uncached.
- **`scan_item`** (`order_receipt.py:217`) — a cached "not found" would push the user into
  the New Product creation flow for a product that was created seconds earlier by a
  colleague at the next bench, producing duplicate Ascend records. If a cache is ever added
  here it must be positive-results-only, short-TTL, and invalidated by
  `create_vendor_product` and `NewProduct.after_insert`.
- **`db_insert` / `db_update` read-back paths** and the `get_latest()` comparison in
  `_resolve_linked_id_fields` (`:670`) — that comparison exists specifically to detect a
  changed value, and a stale read there would skip a needed foreign-key write.

---

## Part B — Existing caching behavior that doesn't use Frappe Redis caching

### B1. `MSSQLDatabase.value_cache` — allocated, cleared, never used

`SQLServer.py:50`

```python
# Value cache mirrors frappe.db.value_cache for short-lived result caching.
self.value_cache = recursive_defaultdict()
```

It is cleared in `commit()` (`:158`) and `rollback()` (`:171`) and **read or written
nowhere in the app**. It is a placeholder mirroring `frappe.db`'s interface. Since each
`MSSQLDatabase` instance lives for exactly one `with` block, an instance-level cache could
never have served a second call anyway. Either wire it to something real (it would need to
outlive the instance to matter — i.e. be Redis) or delete it; as-is it implies a caching
behavior that does not exist.

### B2. `AbstractVirtualDocType._normalized_schema_configs` — correct as-is

`virtual_doctype_base.py:95-114`. A per-process, class-keyed memo of the normalized
`SCHEMA_CONFIG`.

**This should stay local.** It caches a pure function of code (not data), it is invalidated
by process restart, which is exactly when the code can change, and Redis would add
serialization cost to something that is a dict lookup. The comment explaining why it is a
dict on the base class rather than a class attribute is correct and worth keeping. No action.

### B3. `_ascend_field_cache` — instance-level memo, no cross-request reuse

`location_inventory.py:16`, `ski_with_bindings.py:14`.

`hasattr`-guarded memoization on the document instance. It works for its stated purpose
(collapsing several virtual-field properties into one query per row) but:

- it dies with the instance, so nothing is shared between rows, requests, or users (see A5);
- because the guard is `hasattr` rather than a sentinel, the memo also survives an
  in-place reload of the same instance, silently serving pre-reload values.

This is the pattern documented in `VIRTUAL_DOCTYPE_DEVELOPMENT.md` § "virtual fields on a
child table", so any change here should update that doc too.

### B4. `Order Receipt.cached_vendor_id` — a persisted cache with no invalidation  ⚠️

`order_receipt.py:19-24`, field `cached_vendor_id` (Data, read-only) on
`order_receipt.json`.

```python
def validate(self):
    if not self.cached_vendor_id:
        vendor_record = Vendor.get_values(name=self.vendor, fields=['id'])
        ...
        self.cached_vendor_id = vendor_record.id
```

This is a hand-rolled cache of `Vendor.id` stored in MariaDB. Two problems:

1. **It is never invalidated when `vendor` changes.** The refill is gated on
   `not self.cached_vendor_id`, so editing an existing receipt's vendor leaves the *previous*
   vendor's Ascend ID in place. That stale ID is then passed to `scan_item` (`:233`,
   filtering `VendorProducts.VendorID`), to `generate_vpn` (`order_receipt.js:214`), and to
   `create_vendor_product` via `link_vendor_product` (`:288`) — i.e. a Vendor Product could
   be **created in Ascend against the wrong vendor**. A one-line fix
   (`if not self.cached_vendor_id or self.has_value_changed("vendor")`) closes it
   independently of any caching work.
2. It leaks a cache into the document schema and the client payload
   (`order_receipt.js:214, 294` read it off `frm.doc`), and produces the user-facing error
   *"Re-save the document to populate it"* (`:223`, `:283`) — a cache miss surfaced as a
   user instruction.

A Redis cache of vendor-name → Ascend ID (A2) would let this field, both throw sites, and
both client-side reads disappear.

### B5. `order_items.description` / `upc` snapshot — deliberate, and correct

`order_receipt.py:46-61` (`populate_item_snapshot`), `order_receipt_item.py:8-10`.

Denormalized copies of the Vendor Product's description/UPC, written once at add/edit time
so loads never re-query Ascend. The comment records that the per-row lookup "was the main
receiving-job performance bottleneck."

**Keep this as-is.** It isn't really a cache — a receipt is a historical record, and the
description as-of receiving is arguably the *correct* value to retain even if Ascend later
changes it. Redis would be strictly worse here (a receipt outlives any TTL). Worth noting
that `update_table` explicitly clears both fields before re-snapshotting (`:138`) precisely
because `vpn` may have changed — the invalidation discipline B4 is missing.

### B6. `print_labels`' `document_cache` dict

`label_printing/__init__.py:116-125`. A local dict keyed `(doctype, name)`, deduping
repeated items within a single print call. Correct and cheap for its scope; the
cross-call/cross-user reuse is what A6 addresses.

### B7. `virtual_link_title._read_fields` → `frappe.get_cached_doc` — an invalidation gap

`monkey_patches/virtual_link_title.py:160`.

This one *does* route through Frappe's caching — and that is worth a second look rather
than a pat on the back. Frappe's document cache is local + Redis-backed, so a **virtual**
DocType's document (data owned by Ascend, not by Frappe) may be sitting in Redis, and the
only thing that evicts it is a Frappe-side save of that document or a full cache clear.
Ascend-side edits will not.

In practice this is mostly benign — link *titles* are display strings — but it means the app
already has an unbounded-TTL Redis cache of Ascend data that nobody designed as one.

**Verify before acting:** whether this Frappe version stores virtual-DocType documents in
the Redis document cache or only in `frappe.local`, and whether `Document.clear_cache` fires
on the virtual `db_update` path. Check `frappe/__init__.py` (`get_cached_doc`,
`can_cache_doc`, `_set_document_cache`) in the installed bench. The answer decides whether
A5/A6 can lean on `get_cached_doc` or need their own keys with explicit TTLs.

### B8. Already-correct Frappe caching (no action)

- `new_product.py:143, 238` — `frappe.get_cached_doc("Description Template", …)`
- `new_product.py:263` — `frappe.get_cached_doc("Product Pricing Rule", …)`
- `frappe.get_meta` in `child_doctype_for_table` / `writable_fieldnames`
  (`order_receipt.py:68, 79`) and `resolve_to_native` (`resolution.py:210`) — Frappe's meta
  cache is Redis-backed already.
- `is_virtual_doctype` is `@site_cache`d by Frappe (noted in `MONKEY_PATCH.md:194`).

### B9. Client side — no caching, and mostly fine

No `localStorage`/`sessionStorage` caching exists anywhere in `bullwheel/public/js` or the
DocType scripts. `frappe.model.user_settings` in `printing.js:101` persists the last-used
printer per media type — that is preference storage, not a cache.

Two client-side reads worth a mention, both of which become free once A5/A6 land:
`order_receipt.js:453` (`frappe.db.get_value('Vendor Product', vpn, 'product')` on "Open
Product" — one SQL Server query per click, through the monkey patch) and
`ascend_product.js:75` (`Product Price` lookup per form load).

### B10. `cache: True` — a cacheability contract with no consumer

`schema_config.py:41`, `virtual_doctype_base.py:146`,
`VIRTUAL_DOCTYPE_DEVELOPMENT.md:80` all describe `cache` as "safe to cache", and all three
say nothing reads it. It is currently declared on `Vendor.id`, `Vendor.creator_id`,
`Vendor.date_created`, `AscendProduct.name`/`id`/`creator_id`/`date_created`,
`ProductCategory.database_id`/`creator_id`/`date_created`, `VendorProduct.id`/`creator_id`/
`date_created`.

That is the right set for an indefinite-TTL cache, and `cache_fields()` is the hook a
caching layer would build on. Worth noting that `AscendProduct` declares `name` (`Store UPC`)
static while `store_sku` maps to the same column without the flag, and `Vendor.name`/
`vendor_name` (both `Vendors.Name`) carry no flag — so the declarations need an audit pass
before anything trusts them.

---

## Part C — Suggested shape, if this is pursued

A small module (`bullwheel/ascend/cache.py`) owning keys, TTLs, and invalidation, so caching
lives at the framework's existing choke points rather than being sprinkled across
controllers:

- **Namespaced hash keys** — `bullwheel:ascend:<doctype>:<purpose>` via
  `frappe.cache.hset`/`hget`, so `delete_key` can drop one DocType's entire namespace on a
  write without touching the rest.
- **Three TTL tiers**, matched to what Ascend can change underneath us:
  *cache* (`cache_fields()`, hours/indefinite) · *reference* (Categories, Vendors, ~15–60
  min) · *volatile* (list/count results, 30–60 s).
- **Write-side invalidation** in `db_insert`/`db_update` (`virtual_doctype_base.py:706, 743`)
  and `create_vendor_product` (`vendor_product.py:131`) — the three places Bullwheel writes
  Ascend. Everything else rides its TTL.
- **A flush hook** on `after_migrate` and a `bench --site … clear-ascend-cache` command
  alongside the existing `introspect-schema` command in `commands.py`, so a stale cache is
  never a puzzle to clear.
- **Nothing secret in Redis** — the decrypted SQL Server password stays request-scoped (A1).
- **Measure first.** The report ranks by structural reasoning about call counts, not by
  measured latency. Before building the layer, instrument `MSSQLDatabase.sql` (the single
  choke point for every Ascend query) to log query count and duration per request, then run a
  receiving session and a `Warehouse Location` form load. That gives real numbers for the A1
  connection overhead versus the A4/A5 query costs, and tells you whether connection reuse
  or result caching is the better first investment.

---

## Appendix — Quick reference

**Every SQL Server entry point in the app** (each one currently opens its own connection):

| Location | Method |
|---|---|
| `virtual_doctype_base.py:406` | `load_from_db` |
| `virtual_doctype_base.py:439` | `get_values` |
| `virtual_doctype_base.py:522` | `get_list` |
| `virtual_doctype_base.py:563` | `get_count` |
| `virtual_doctype_base.py:734` | `db_insert` |
| `virtual_doctype_base.py:769` | `db_update` |
| `order_receipt.py:235` | `scan_item` (2 queries, 1 connection) |
| `vendor_product.py:82` | `vendor_product_match_count` |
| `vendor_product.py:124` | `generate_vpn` (N queries, 1 connection) |
| `vendor_product.py:141` | `create_vendor_product` |
| `schema_introspection.py` | `introspect_table_schema` / `introspect_join_schemas` |

**Existing cache-like mechanisms:**

| Mechanism | Location | Scope | Uses Frappe Redis? |
|---|---|---|---|
| `_normalized_schema_configs` | `virtual_doctype_base.py:95` | Per process | No — correct as-is |
| `value_cache` | `SQLServer.py:50` | Per instance | No — dead code |
| `_ascend_field_cache` | `location_inventory.py:16`, `ski_with_bindings.py:14` | Per document instance | No |
| `cached_vendor_id` | `order_receipt.py:22` | Persisted in MariaDB | No — and never invalidated |
| `description`/`upc` snapshot | `order_receipt.py:46` | Persisted in MariaDB | No — deliberate, keep |
| `document_cache` | `label_printing/__init__.py:116` | Per print call | No |
| `get_cached_doc` fallback | `virtual_link_title.py:160` | Request + Redis | Yes — with an invalidation gap |
| `get_cached_doc` | `new_product.py:143, 238, 263` | Request + Redis | Yes — correct |
