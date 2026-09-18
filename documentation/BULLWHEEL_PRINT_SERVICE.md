# Bullwheel Print Service — Requirements and Contract

The **Bullwheel Print Service** is a Windows 11 application that runs on a computer with a USB-attached Zebra label printer. It receives ZPL from Bullwheel and sends it to that printer.

Bullwheel sends ZPL to the service in one of two ways, depending on the `Label Printer`'s **Connection Method**. The service must handle both:

| Connection Method | Who connects | Transport | Where Bullwheel defines it |
|---|---|---|---|
| **USB** | The Frappe **server** | Raw TCP, port **9100** | `ZebraPrinter.USB_PRINT_SERVICE_PORT` in `bullwheel/label_printing/ZebraPrinter.py` |
| **Browser** | The user's **browser**, on the same computer | HTTP `POST /print`, `127.0.0.1:9110` | `BROWSER_PRINT_SERVICE_URL` in `bullwheel/public/js/utils/printing.js` |

In both cases Bullwheel has already rendered the ZPL. The service never renders templates or looks up data. It receives finished ZPL and sends it to the printer unchanged.

Requirements use **must** (Bullwheel breaks without it), **should** (strongly recommended), and **may** (optional).

---

## 1. General requirements

1. **Platform.** The service must run on Windows 11. It should run as a Windows service that starts at boot, not as a program someone has to launch.
2. **One process, both listeners.** The service must run the USB (TCP) listener and the Browser (HTTP) listener at the same time.
3. **Printing.** The service must send the ZPL to the Windows printer as **RAW** data through the Windows spooler (e.g. `win32print` with the `RAW` datatype), so the driver doesn't reinterpret it. Bytes must be sent exactly as received.
4. **Encoding.** Bullwheel encodes ZPL as **UTF-8**. The service must pass those bytes through without re-encoding.
5. **One job at a time per printer.** Jobs from both listeners can target the same printer. The service must send each job to the spooler as a single job, and must not interleave two jobs' bytes on one printer.
6. **Choosing the printer.** The service must know which Windows printer to use. At minimum it needs one configured **default printer**. For the Browser method it should also support a mapping from Bullwheel `printer_name` to a Windows printer name (see §3.4).
7. **Configuration.** The following must be configurable without a code change:
   - the default Windows printer
   - the printer-name mapping
   - the TCP port (default 9100)
   - the HTTP port (default 9110)
   - the allowed browser origins (§3.5)
8. **Logging.** The service should log every job: time, source (USB or Browser), `printer_name` when given, target Windows printer, byte count, and the result. It must log every failure with its reason.
9. **Ports.** The two listeners must use different ports. **9100 is taken by the USB listener**, so the HTTP listener cannot use it.

---

## 2. USB method — raw TCP listener

This interface already exists in Bullwheel and doesn't change. The Frappe server connects to the service as if it were a network Zebra printer.

### 2.1 Listener

- The service must listen for TCP on **port 9100**.
- The Frappe server connects over the network, from the Docker host. So the listener must bind to the computer's LAN or tailnet interface, **not only** to `127.0.0.1`.
- Windows Firewall must allow inbound TCP 9100 from the Frappe server. The service's installer should create that rule, limited to the server's address where practical.
- In Bullwheel, the `Label Printer` record's **Connected Computer Address** holds this computer's address.

### 2.2 Print job

This is what the server does (`ZebraPrinter.connect` / `send` / `close`):

1. It opens a TCP connection, waiting up to the printer's **Connection Timeout** (default 5 s).
2. It sends the entire job in one `sendall`: every label for the request, concatenated.
3. It closes the connection. **It never reads a reply.**

The service must:

- read until the server closes the connection (EOF), then treat everything received as **one job**
- print it as described in §1
- accept any number of connections over time; each connection is one job

The server can't see whether printing worked. Any failure after the connection is accepted is visible only in the service's log.

### 2.3 Test Connection (`~HS`)

The **Test Connection** button works differently:

1. The server connects and sends only `~HS` (Zebra Host Status).
2. It **does not close**. It waits up to the connection timeout for a reply of up to three status strings, each wrapped in STX (`0x02`) … ETX (`0x03`).
3. Then it closes.

Bullwheel accepts either behaviour:

| Service behaviour | What the user sees |
|---|---|
| Stays silent (**minimum requirement**) | Green "reachable". The test waits out the full timeout first. |
| Relays the printer's real `~HS` reply | Paper-out, paused and head-open are reported accurately (orange if any are set). |

So the service **must** accept the connection and must not crash on a `~HS`-only job. It **may** detect a payload that is exactly `~HS`, query the printer, and write the reply back before the server closes. A service that only reads until EOF won't see `~HS` until the server gives up and closes. If it then forwards `~HS` to the printer, that is harmless.

---

## 3. Browser method — HTTP listener

This interface is new. The user's browser, running Bullwheel, sends ZPL the server has already rendered to the service on the **same computer**. The server never contacts the service.

### 3.1 Listener

- The service must serve HTTP on **`127.0.0.1:9110`**.
- It must bind to **loopback only**. This endpoint is only for browsers on the same computer and must not be reachable from the network.
- Plain HTTP is fine. Browsers treat `http://127.0.0.1` as a trustworthy origin, so it can be called from the HTTPS production site without mixed-content blocking.
- If the port changes, `BROWSER_PRINT_SERVICE_URL` in `printing.js` must change to match, and Bullwheel must be rebuilt.

### 3.2 Request

```
POST /print HTTP/1.1
Host: 127.0.0.1:9110
Origin: https://<bullwheel host>
Content-Type: application/json

{"printer_name": "Front Desk", "media_type": "Direct Thermal", "dpi": 203, "zpl": "^XA...^XZ^XA...^XZ"}
```

| Field | Type | Always present | Meaning |
|---|---|---|---|
| `printer_name` | string | yes | Name of the Bullwheel `Label Printer` the user chose. Use it to pick the Windows printer (§3.4). |
| `media_type` | string or `null` | yes (may be `null`) | The Label Printer's Media Type: `"Direct Thermal"` or `"Thermal Transfer"`. `null` when not set in Bullwheel. |
| `dpi` | integer | yes | The Label Printer's DPI (e.g. `203`, `300`). Bullwheel laid the label out for this resolution. |
| `zpl` | string | yes | The finished ZPL for every label in the request, concatenated. Copies are already encoded in the ZPL (`^PQ`). Send it as-is. |

The service must:

- accept only `POST /print` and return `404` or `405` for anything else
- reject a request whose `Content-Type` isn't `application/json` with `415` (this is a security requirement — see §3.5)
- reject malformed JSON, a missing field, or an empty `zpl` with `400`
- ignore unknown fields, so Bullwheel can add fields later without breaking older services

The service should not trust `media_type` or `dpi` to change the job. It may use them to warn, for example logging a mismatch or returning `409` when the target Windows printer is known to have a different resolution.

### 3.3 Response

| Outcome | Status | Body |
|---|---|---|
| Job accepted by the Windows spooler | any **2xx** (`200` or `204`) | Ignored by Bullwheel. |
| Anything else | any **non-2xx** | **Plain text, one short sentence**, e.g. `Printer "ZD421-Front" is offline.` |

- Bullwheel treats **any 2xx as printed**. It shows a green alert.
- On **any non-2xx**, Bullwheel shows a red alert plus a dialog with the status code and the body text, HTML-escaped. So the body should be a message someone at the counter can act on, not a stack trace.
- If the connection fails (service not running, port closed, CORS rejected), Bullwheel tells the user the Bullwheel Print Service must be running on this computer.
- The service should respond **once the job is handed to the spooler**, not after the label physically prints. Bullwheel sets no request timeout, so the user waits as long as the service takes. Keep it to a few seconds at most.
- Suggested codes:
  - `400`: bad payload
  - `415`: wrong content type
  - `404`: no Windows printer resolved for `printer_name` and no default configured
  - `503`: printer offline, spooler error
  - `500`: anything unexpected

### 3.4 Choosing the Windows printer

The service should pick the Windows printer in this order:

1. The configured mapping entry for `printer_name`.
2. The configured default printer.
3. Otherwise, fail with `404` and a message such as `No printer is configured for "Front Desk".`

In Bullwheel, one Browser `Label Printer` record can be shared by many users on different computers. It is effectively a profile holding DPI and media type. So the same `printer_name` will reach many different services, and each computer resolves it to its own printer. For computers with a single Zebra printer, a default alone is enough.

### 3.5 CORS, Private Network Access and security

The Bullwheel page and the service have different origins, and the request uses `Content-Type: application/json`, so **browsers send a CORS preflight first**. Without correct preflight handling, the browser blocks the request and Bullwheel reports the service as unreachable.

**Preflight.** The service must answer `OPTIONS /print` with a `204` and these headers:

```
Access-Control-Allow-Origin: <the request's Origin, if it is allowed>
Access-Control-Allow-Methods: POST
Access-Control-Allow-Headers: Content-Type
Access-Control-Allow-Private-Network: true
Access-Control-Max-Age: 600
Vary: Origin
```

`Access-Control-Allow-Private-Network: true` is required by Chrome and Edge **Private Network Access**. When a public HTTPS page calls a loopback address, the preflight may include `Access-Control-Request-Private-Network: true`, and without this response header the browser blocks the request.

**Actual response.** The `POST` response (success *and* error) must also carry `Access-Control-Allow-Origin` and `Vary: Origin`. Otherwise the browser hides the status and body from Bullwheel, and a readable error turns into "could not be reached."

**Allowed origins.** An endpoint that prints for any caller would let *any website* the user visits send labels to their printer. So the service must:

- keep a configurable allow-list of origins, e.g.:
  - `https://<production Bullwheel host>`
  - `http://barriesdev.localhost:8000` (development)
- echo the request's `Origin` back in `Access-Control-Allow-Origin` **only** when it is on the list. **Do not use `*`.**
- reject a `POST` whose `Origin` header is present but not allowed, with `403`, without printing. CORS only stops the browser from *reading* a response; it doesn't stop the request from reaching the service, so this server-side check is what actually prevents the print.
- require `Content-Type: application/json` (§3.2). A cross-site page could otherwise send a `text/plain` "simple request" that skips the preflight entirely.

With loopback-only binding (§3.1), these rules mean only Bullwheel pages open on the same computer can print.

---

## 4. Acceptance checklist

**USB method**

- [ ] With a USB `Label Printer` pointed at this computer, *Print Ascend Tag* in Bullwheel prints the correct label.
- [ ] A request with several items and quantities prints every label once, as one spooler job.
- [ ] *Test Connection* reports reachable, and the service logs the `~HS` job without error.
- [ ] Port 9100 is reachable from the Frappe server and blocked from other hosts, if restricted.

**Browser method**

- [ ] With a Browser `Label Printer`, printing from Bullwheel shows a green alert and the label prints.
- [ ] The service log shows `printer_name`, `media_type` and `dpi` matching the Label Printer record.
- [ ] With the service stopped, Bullwheel shows the red "Bullwheel Print Service" message.
- [ ] With the printer unplugged or paused, the service returns a non-2xx with a readable message, and that message appears in Bullwheel.
- [ ] Works from the **production HTTPS site** in Chrome and Edge. This exercises the CORS and Private Network Access preflight.
- [ ] Port 9110 is **not** reachable from another computer.
- [ ] A `POST` from a page on a non-allowed origin is rejected with `403` and nothing prints.
- [ ] A `POST` with `Content-Type: text/plain` is rejected with `415` and nothing prints.

**Both**

- [ ] A USB job and a Browser job sent to the same printer at the same moment both print, and neither label is corrupted.

---

## 5. Keeping Bullwheel and the service in step

| Setting | Bullwheel location | Must match |
|---|---|---|
| TCP port (USB method) | `ZebraPrinter.USB_PRINT_SERVICE_PORT` — `bullwheel/label_printing/ZebraPrinter.py` | Service TCP port |
| HTTP URL (Browser method) | `BROWSER_PRINT_SERVICE_URL` — `bullwheel/public/js/utils/printing.js` | Service HTTP port and path |
| Payload fields | `print_labels` in `bullwheel/label_printing/__init__.py` (the `"browser"` return value) | §3.2 |

For how Bullwheel produces these jobs, see `LABEL_PRINTING.md`.
