# Label Printing (Zebra / ZPL)

The **Label Printing** module prints to Zebra printers using **raw ZPL over a TCP socket** — no driver, spooler, or CUPS on the Bullwheel side. There is **no extra dependency**: the transport is Python's stdlib `socket`. Zebra printers listen on port **9100** and execute whatever ZPL bytes arrive.

The transport deliberately mirrors the SQL Server handler pattern (`MSSQLDatabase`), so the same conventions apply.

**Connection methods** — the `Label Printer.connection_method` field (`Network` / `USB`) selects the socket endpoint; `ZebraPrinter` resolves it once in `__init__` into `target_host`/`target_port`:

- **Network** → the printer's own ZPL listener at `ip:port` (default `:9100`).
- **USB** → the **Bullwheel USB Print Service** at `connected_computer_address:9100`. The USB printer has no network port, so a small Windows-side relay service listens on TCP 9100 and forwards raw ZPL to the local printer via the Windows spooler (win32print RAW). From `ZebraPrinter`'s view both methods are identical — a fire-and-forget TCP send. The service port is fixed in `ZebraPrinter.USB_PRINT_SERVICE_PORT` (9100) and must match the service's `--port`.

## Files

| File | Role |
|---|---|
| `label_printing/ZebraPrinter.py` | `ZebraPrinter` — the transport primitive. Constructed from a `Label Printer` doc; resolves `target_host`/`target_port` from `connection_method`; context-manager `connect`/`close`; `send(zpl)`; `get_host_status()` / `test_connection()`. |
| `label_printing/exceptions.py` | `PrinterException` base + `PrinterConnectionError`, `PrinterSendError`, `PrinterStatusError`; `LabelResolutionError` (a data problem, not a transport problem). |
| `label_printing/__init__.py` | Whitelisted `test_connection` (msgprint green/orange/red) and `print_labels` — the app-wide print entry point; guards against `disabled` printers, resolves items, renders, sends once. |
| `label_printing/resolution.py` | Server-side resolution of print items to natively printable documents (the `LABEL_RESOLUTION_FIELD` hop logic). |
| `label_printing/doctype/label_printer/` | `Label Printer` — device config (see below). `label_printer.js` adds the **Test Connection** form button. |
| `label_printing/doctype/zebra_printer_label/` | `Zebra Printer Label` — the template layer: `zpl` (Text) holds a **Jinja template** rendered per document; `render(doc, printer, quantity)` supplies `doc`, `printer`, `label`, `quantity` as context. |
| `label_printing/doctype/zebra_printer_label_target/` | Child rows of the `target_doctypes` multiselect (below). |
| `public/js/utils/printing.js` | Client framework: `bullwheel.printing.add_print_button` (forms) and `bullwheel.printing.add_list_print_button` (list views). Loaded globally via `utilities.bundle.js` / `app_include_js`. |
| `fixtures/zebra_printer_label.json` | Default label templates (Ascend Tag, Swap Tag, Warehouse Location). |

**`Label Printer` DocType** — device config: `printer_name` (autoname, unique), `connection_method` (Network/USB), `connected_computer_address` (USB only), `ip`/`port` (Network only, default 9100), `timeout` (default 5s), `dpi`, `type` (Direct Thermal / Thermal Transfer), `location`, `disabled`. Network vs USB fields are toggled via `depends_on` / `mandatory_depends_on` on `connection_method`.

## Label templates and slots

ZPL layouts live in **`Zebra Printer Label`** records as Jinja templates (`zpl` Text field). The template receives `doc` (the resolved source document), `printer` (for `dpi`), `label` (for `width`/`height`), and `quantity` (emit it as `^PQ{{ quantity }}`). Which template a print request uses is data-driven: **Bullwheel Settings ▸ Printing ▸ Labels** has one Link field per *slot* — `ascend_tag`, `online_tag`, `swap_tag`, `warehouse_location` — each pointing at a `Zebra Printer Label`.

**`target_doctypes`** (Table MultiSelect on `Zebra Printer Label`) declares which DocTypes the template is designed to render — one template may serve several DocTypes as long as the field names its Jinja reads exist on all of them. When set, print requests whose items do not resolve to one of these DocTypes are rejected *before anything prints*; when empty, any document is accepted. The list also stops resolution early: a doctype the label explicitly targets is printable as-is, even if it declares a resolution field of its own.

## Label Printing Framework

### Native vs Resolved DocTypes

- **Native** doctypes are the ones label templates render directly (e.g. **Ascend Product**, **Warehouse Location**).
- **Resolved** doctypes carry a Link or Dynamic Link field that eventually reaches a Native doctype. Their controller class declares which field to follow:

```python
class VendorProduct(AbstractVirtualDocType):
	LABEL_RESOLUTION_FIELD = 'product'  # Link → Ascend Product

class OrderReceiptItem(Document):
	LABEL_RESOLUTION_FIELD = 'vpn'      # Dynamic Link via item_type
```

Native doctypes declare nothing. The server hops these fields until it reaches a doctype with no declaration (or one in the label's `target_doctypes`):

```
Order Receipt Item ── vpn (Dynamic Link via item_type) ──▶ Vendor Product ── product ──▶ Ascend Product
```

The client therefore never round-trips to translate a selection: it sends whatever identifiers are in scope and the server (`label_printing/resolution.py`) does the rest. A visited-set plus depth cap (10) turns cyclic or runaway chains into a clear error.

**All-or-nothing:** if *any* requested item fails to resolve (broken link, dead end, target mismatch), `print_labels` throws naming every failing item and **nothing prints** — a mixed selection never partially prints on a shared printer.

### Server entry point: `print_labels`

`bullwheel.label_printing.print_labels` — the only print entry point; never touch `ZebraPrinter` from client code.

| Argument | Meaning |
|---|---|
| `printer_name` | `name` of the chosen `Label Printer`. Disabled printers are rejected. |
| `slot` | Bullwheel Settings ▸ Printing ▸ Labels slot: `ascend_tag`, `online_tag`, `swap_tag`, `warehouse_location`. |
| `items` | List (or JSON string) of `{doctype?, name, quantity?}` dicts. `quantity` defaults to 1; `quantity: 0` skips the item. |
| `doctype` | Optional default for items that carry no `doctype` of their own. |

Duplicate items resolving to the same native document are fetched once and rendered per requested quantity; all rendered ZPL is concatenated and sent in a single transmission.

### Client utilities (`bullwheel.printing`)

Both utilities share the same flow: normalize the items → show the **print dialog** (a required `Label Printer` link plus an editable grid of the items with per-item **Quantity**; deleting a row or setting its quantity to 0 skips that item) → one `frappe.call` to `method`.

**Items contract** — `items` may be given as any of:

```
• omitted                                → the form's own document (form buttons only)
• 'DOCNAME'                              → one item
• ['DOCNAME-A', 'DOCNAME-B']             → many items
• [{doctype?, name, quantity?, label?}]  → full form
• a (possibly async) callback returning any of the above; receives `frm`
```

Per item: `doctype` defaults to the top-level `doctype` argument (which defaults to the form's / list view's own doctype); `label` is display-only dialog text (defaults to `name`). A callback that resolves no items is a normal outcome: the user sees `empty_message` and nothing is printed.

**`add_print_button`** — form views:

| Option | Meaning |
|---|---|
| `frm` | The form the button is added to (required). |
| `label` | Button text, also the dialog title (required). |
| `slot` | Label slot (required). |
| `doctype` | Default doctype for the items; a value or a callback. Defaults to the form's own DocType. |
| `items` | Items per the contract above. Defaults to the form's own document. |
| `group` | Custom button group. Defaults to `'Print Labels'`. |
| `empty_message` | Shown when a callback resolves no items (e.g. nothing selected). |
| `method` | Whitelisted server action. Defaults to `'bullwheel.label_printing.print_labels'`. |

**`add_list_print_button`** — list views. Registers in the **Actions** menu, which Frappe shows only while rows are checked; the checked rows become the items. Options are the same minus `frm`/`group`/`items`, plus `listview` (required); `doctype` defaults to `listview.doctype`.

> No list view ships with print actions yet. To add one, create `<doctype>_list.js` beside the doctype (Frappe auto-loads it):

```js
// e.g. bullwheel/ascend/doctype/ascend_product/ascend_product_list.js
frappe.listview_settings['Ascend Product'] = {
	onload(listview) {
		bullwheel.printing.add_list_print_button({ listview, label: 'Print Swap Tag', slot: 'swap_tag' });
		bullwheel.printing.add_list_print_button({ listview, label: 'Print Ascend Tag', slot: 'ascend_tag' });
	},
};
```

### Worked examples (the four print types)

| Print type | Example | Call |
|---|---|---|
| Native Self | Warehouse Location form | `bullwheel.printing.add_print_button({ frm, label: 'Print Label', slot: 'warehouse_location' })` — `warehouse_location.js` |
| Native Selection | Ascend Product list view | The `add_list_print_button` snippet above (not yet shipped). |
| Resolved Self | Vendor Product form | Same one-liner as Native Self — the server follows `product` to the Ascend Product. `vendor_product.js` |
| Resolved Selection | Order Receipt order-items grid | `items` callback maps selected rows to `{doctype: row.item_type, name: row.vpn, label: row.description}` — `order_receipt.js` |

## Conventions

- **`ZebraPrinter` is transport, not templating.** Layouts live in `Zebra Printer Label` Jinja; `print_labels` renders and sends.
- **Add print buttons only via `bullwheel.printing.add_print_button` / `add_list_print_button`** — never hand-roll a `frappe.call` to the print method, and never touch `ZebraPrinter` from client code.
- **Health check uses `~HS` (Host Status).** `get_host_status` parses paper-out / paused / head-open flags. A silent target — a printer that doesn't reply, or the **send-only USB service** (which never returns status) — is treated as **reachable-but-unknown**, not a failure. So USB printers always report "reachable, status unknown"; network printers get full status.
- **Sanitize interpolated values** — strip `^` and `~` (ZPL command prefixes) from any user/data string placed into ZPL. Do this inside the Jinja template (`| replace('^',' ') | replace('~',' ')`).
- **Geometry comes from the printer's `dpi`, computed in the template.** ZPL positions are in dots and ZPL cannot do arithmetic, so templates derive dot dimensions in Jinja from `printer.dpi` and `label.width`/`label.height` (e.g. `{%- set W = (label.width * printer.dpi) | int -%}`).
- **Centering:** `^FB<label_width>,1,0,C` at `^FO0,y` centers **text** fields — but **not** barcodes. `^FB` never moves a barcode's bars; they always start at the `^FO` origin. Center a barcode manually: estimate its width (Code 128 ≈ `(11 * chars + 35) * module_width` dots) and set `^FO<(label_width - barcode_width) / 2>,y`.
- No default-printer concept yet; the print dialog asks every time.
