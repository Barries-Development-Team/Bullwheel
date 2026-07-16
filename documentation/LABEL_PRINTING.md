# Label Printing (Zebra / ZPL)

The **Label Printing** module prints to Zebra printers using **raw ZPL over a TCP socket** — no driver, spooler, or CUPS on the Bullwheel side. There is **no extra dependency**: the transport is Python's stdlib `socket`. Zebra printers listen on port **9100** and execute whatever ZPL bytes arrive.

The module deliberately mirrors the SQL Server handler pattern (`MSSQLDatabase`), so the same conventions apply.

**Connection methods** — the `Label Printer.connection_method` field (`Network` / `USB`) selects the socket endpoint; `ZebraPrinter` resolves it once in `__init__` into `target_host`/`target_port`:

- **Network** → the printer's own ZPL listener at `ip:port` (default `:9100`).
- **USB** → the **Bullwheel USB Print Service** at `connected_computer_address:9100`. The USB printer has no network port, so a small Windows-side relay (`usb_print_service/`) listens on TCP 9100 and forwards raw ZPL to the local printer via the Windows spooler (win32print RAW). From `ZebraPrinter`'s view both methods are identical — a fire-and-forget TCP send. The service port is fixed in `ZebraPrinter.USB_PRINT_SERVICE_PORT` (9100) and must match the service's `--port`.

## Files

| File | Role |
|---|---|
| `label_printing/ZebraPrinter.py` | `ZebraPrinter` — the transport primitive. Constructed from a `Label Printer` doc; resolves `target_host`/`target_port` from `connection_method`; context-manager `connect`/`close`; `send(zpl)`; `get_host_status()` / `test_connection()`. |
| `label_printing/exceptions.py` | `PrinterException` base + `PrinterConnectionError`, `PrinterSendError`, `PrinterStatusError`. |
| `label_printing/__init__.py` | Whitelisted `test_connection` (msgprint green/orange/red) and `print_label` — the app-wide print entry point; guards against `disabled` printers. |
| `label_printing/doctype/label_printer/label_printer.js` | **Test Connection** form button. |


**`Label Printer` DocType** — device config: `printer_name` (autoname, unique), `connection_method` (Network/USB), `connected_computer_address` (USB only), `ip`/`port` (Network only, default 9100), `timeout` (default 5s), `dpi`, `type` (Direct Thermal / Thermal Transfer), `location`, `disabled`. Network vs USB fields are toggled via `depends_on` / `mandatory_depends_on` on `connection_method`.

## Conventions

- **Send raw ZPL only.** Callers supply the ZPL string; the handler is transport, not templating. ZPL *content generation* (label layouts from product data) is a separate, not-yet-built layer.
- **Print via the whitelisted `print_label`**, never by touching `ZebraPrinter` from client code. Example caller: the **Print Label** button in `warehouse_location.js` (prompts for a `Label Printer`, then calls `print_label` — the reference pattern for adding a print button to any DocType).
- **Health check uses `~HS` (Host Status).** `get_host_status` parses paper-out / paused / head-open flags. A silent target — a printer that doesn't reply, or the **send-only USB service** (which never returns status) — is treated as **reachable-but-unknown**, not a failure. So USB printers always report "reachable, status unknown"; network printers get full status.
- **Sanitize interpolated values** — strip `^` and `~` (ZPL command prefixes) from any user/data string placed into ZPL.
- **Geometry comes from the printer's `dpi`, resolved at build time.** ZPL positions are in dots, and ZPL cannot do arithmetic, so any dot dimension derived from inches (e.g. a 2" width = `2 * dpi`) must be computed where `dpi` is a real number. The label builder fetches the selected printer's `dpi` (`frappe.db.get_value('Label Printer', ...)`) and computes dimensions before assembling the ZPL — `print_zpl` stays pure transport and does no substitution.
- **Centering:** `^FB<label_width>,1,0,C` at `^FO0,y` centers **text** fields — but **not** barcodes. `^FB` never moves a barcode's bars; they always start at the `^FO` origin. Center a barcode manually: estimate its width (Code 128 ≈ `(11 * chars + 35) * module_width` dots) and set `^FO<(label_width - barcode_width) / 2>,y`.
- No default-printer concept yet; callers name the printer explicitly.

## Label Printing Methods

### `print_label`

Located within the Label Printing module; `bullwheel.label_printing.print_label`

Arguments
- `printer_name`: `name` field value of the chosen printer.
- `slot`: DocField name of the corresponding label in Bullwheel Settings.
    - Options include `ascend_tag`, `online_tag`, `swap_tag`, and `warehouse_location`.
- `doctype`: Name of the source DocType.
    - e.g. "Ascend Product", "Warehouse Location"
- `docname`: `name` field value of the chosen DocType.