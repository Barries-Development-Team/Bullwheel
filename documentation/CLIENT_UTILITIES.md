# Client Utilities Bundle

`public/js/utils/utilities.bundle.js` is loaded site-wide via `app_include_js`, so every utility it imports is available on the global `bullwheel` namespace from any page, DocType script, or list view — with no explicit import needed. Each utility file registers itself under its own sub-namespace (`bullwheel.printing`, `bullwheel.warehouse`, …) rather than exporting anything, since DocType/Page scripts have no module system to import from.

## Files

| File | Namespace | Role |
|---|---|---|
| `utils/printing.js` | `bullwheel.printing` | Label-printing dialog + form/list buttons. See [`LABEL_PRINTING.md`](LABEL_PRINTING.md) for full detail. |
| `utils/warehouse.js` | `bullwheel.warehouse` | Item check-in / check-out dialogs, documented below. |

To add a new utility: create `utils/<name>.js` with `frappe.provide('bullwheel.<name>')` at the top, then add `import "./utils/<name>";` to `utilities.bundle.js`.

## `bullwheel.warehouse`

Two dialog-driven entry points for moving stock into or out of a Warehouse Location's on-hand inventory (the `location_inventory_quantities` child table, `Location Inventory` doctype). Both call the whitelisted methods in `bullwheel/warehouse/stock_handler.py`, and both are wired to the **Item Check-In/Out** page (`item-check-in-out`) as its primary/secondary actions, but either can be called from anywhere (e.g. a form's custom button) since they take no `frm`.

### `check_in_item({ on_success })`

Prompts for a **Product** (Link → Ascend Product), a **Warehouse Location** (Link, filtered to leaf locations only — `is_group: 0`, since group locations cannot hold inventory), and a **Quantity** (Int, default 1). On submit, calls `check_in_item` and either increments the existing `Location Inventory` row for that product at that location or appends a new one.

| Option | Meaning |
|---|---|
| `on_success` | Optional callback `(product, location, quantity)` invoked after the server confirms the check-in — for callers that need to refresh something (a grid, a report) without polling. |

```js
bullwheel.warehouse.check_in_item({
	on_success: (product, location, quantity) => console.log(`+${quantity} ${product} @ ${location}`),
});
```

### `check_out_item({ on_success })`

Prompts for a **Product** first. Its `onchange` calls `get_locations_for_product` and populates a **Warehouse Location** Select with only the locations that currently have that product on hand, plus a read-only **On Hand** field that updates as the location selection changes. A **Quantity** field (default 1) rounds out the dialog. Submitting validates client-side that the quantity does not exceed the on-hand amount for the selected location before calling `check_out_item`, which decrements (or removes, if it reaches zero) the matching `Location Inventory` row.

| Option | Meaning |
|---|---|
| `on_success` | Optional callback `(product, location, quantity)` invoked after the server confirms the check-out. |

```js
bullwheel.warehouse.check_out_item();
```

### Server methods (`bullwheel.warehouse.stock_handler`)

| Method | Args | Behavior |
|---|---|---|
| `get_locations_for_product` | `product` | Returns `[{parent, quantity}]` — every Warehouse Location with on-hand quantity of `product`. Also used by the Find Product page. |
| `check_in_item` | `product`, `location`, `quantity` | Loads the `Warehouse Location` document (so its `validate()` still runs), increments/appends the matching `Location Inventory` row, saves. Throws if `quantity <= 0`. |
| `check_out_item` | `product`, `location`, `quantity` | Loads the `Warehouse Location` document, decrements the matching row (removing it at zero), saves. Throws if `quantity <= 0`, if the location has no on-hand quantity of the product, or if `quantity` exceeds what's on hand. |

All three go through `frappe.get_doc(...).save()` rather than raw `frappe.db` writes, specifically so `WarehouseLocation.validate()` (e.g. "group locations cannot hold inventory") is never bypassed by a check-in/check-out call.

### Worked example: Item Check-In/Out page

`item_check_in_out.js` wires both dialogs as page actions — no forms or selections required:

```js
page.set_primary_action('Check In', () => bullwheel.warehouse.check_in_item(), 'add');
page.add_button('Check Out', () => bullwheel.warehouse.check_out_item(), { icon: 'remove' });
```
