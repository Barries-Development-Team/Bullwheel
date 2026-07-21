# Bullwheel

Warehouse and operations management software for [Barrie's Ski and Sports](https://barriessports.com), built as a custom [Frappe Framework](https://frappeframework.com/) v16 app. Bullwheel runs in tandem with the store's [Ascend RMS](https://www.ascendrms.com/) point-of-sale system, connecting to Ascend's Microsoft SQL Server database to extend it with warehouse, receiving, and labeling workflows that Ascend doesn't cover.

This is an internal business tool for Barrie's Ski and Sports. It is not distributed publicly.

## Features

- **Location Tracking** — bin-level inventory locations with a group/leaf hierarchy (`Warehouse Location`, `Location Inventory`)
- **Ski-Binding Pair Tracking** — linked ski/binding combinations sold as a set
- **Swap Sales** — swap and online pricing tracked per product (`Product Price`)
- **Warehouse Fetch / Picklists** — adjusts location and quantity when an item is sold directly from the warehouse
- **Inventory Counting and Scheduling** — daily warehouse bay count assignments
- **Receiving** — single-pass order receipt builder with barcode scanning, new vendor/product staging, and count verification (see [`documentation/RECEIVING_FLOW.md`](documentation/RECEIVING_FLOW.md))
- **Tagging / Label Printing** — Zebra ZPL label printing (swap tags, Ascend tags, warehouse bay labels) over raw TCP, network or USB (see [`documentation/LABEL_PRINTING.md`](documentation/LABEL_PRINTING.md))
- **Description Templates** — Jinja-driven auto-generated product descriptions (see [`documentation/DESCRIPTION_TEMPLATES.md`](documentation/DESCRIPTION_TEMPLATES.md))
- **Automated Online Listings**
- **Data Backups** — automated off-site backups to Google Drive, with scheduled pruning
- **Automated Software Updates** — checks GitHub for new releases
- **Automated Changelog** — see [`CHANGELOG.md`](CHANGELOG.md)
- **Easy Feature Additions** — isolated branch workflow with heavy backend testing

## Architecture

Bullwheel is a standard Frappe app (MariaDB-backed) that additionally bridges live data out of Ascend's SQL Server database:

| Module | Doctypes |
|---|---|
| `database` | `SQL Server` — stores credentials for an Ascend SQL Server connection |
| `ascend` | `Ascend Product` (virtual), `Vendor`, `Vendor Product`, `New Product`, `Product Category`, `Product Price`, `Description Template`, `Order Receipt`, `Order Receipt Item`, `Bulk Product Import`, `Ski With Bindings` |
| `warehouse` | `Warehouse Location`, `Location Inventory` |
| `label_printing` | `Label Printer`, `Zebra Printer Label`, `Zebra Printer Label Target` |
| `bullwheel_core` | `Bullwheel Settings` |

**`MSSQLDatabase`** (`bullwheel/database/SQLServer.py`) is the connection and query execution primitive for Ascend's SQL Server, used via `pymssql`. It mirrors `frappe.db`'s context-manager style without inheriting its MariaDB-coupled implementation. See [`documentation/MSSQLDatabase.md`](documentation/MSSQLDatabase.md).

**Virtual DocTypes** (e.g. `Ascend Product`) surface Ascend SQL Server tables — such as the ~200,000-SKU `Products` table — as native Frappe DocTypes, with Link-field autocomplete, `fetch_from`, and title resolution, without replicating any data into MariaDB. A shared framework (`AbstractVirtualDocType` in `bullwheel/ascend/virtual_doctype_base.py`) derives query logic from a single `SCHEMA_CONFIG` dict per controller. See [`documentation/VIRTUAL_DOCTYPE_DEVELOPMENT.md`](documentation/VIRTUAL_DOCTYPE_DEVELOPMENT.md) for the full guide, and [`documentation/MONKEY_PATCH.md`](documentation/MONKEY_PATCH.md) for the patch that makes "Show Title in Link Fields" work against virtual DocTypes.

Labels are rendered from data-driven `Zebra Printer Label` records and sent as raw ZPL directly to Zebra printers over TCP (no OS driver or spooler); see [`documentation/LABEL_PRINTING.md`](documentation/LABEL_PRINTING.md) and [`documentation/CLIENT_UTILITIES.md`](documentation/CLIENT_UTILITIES.md).

## Requirements

- [Frappe Docker](https://github.com/frappe/frappe_docker) (Frappe Framework v16)
- Python 3.14+
- MariaDB and Redis (managed by Frappe Docker's compose stack)
- Network access to one or more Microsoft SQL Server instances running Ascend RMS
- `pymssql` (bundles FreeTDS — no OS-level ODBC driver needed inside the container)

## Installation

Bullwheel is installed as an app into a Frappe bench, per the standard [bench](https://github.com/frappe/bench) workflow:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench --site $SITE_NAME install-app bullwheel
```

`pymssql` must also be installed into the bench's Python environment (it is listed in this app's dependencies, so it survives container rebuilds, but a fresh environment may need it installed manually):

```bash
cd /workspace/frappe-bench
./env/bin/pip install pymssql
```

### Production deployment (Frappe Docker)

All build and compose commands below are run from within a [Frappe Docker](https://github.com/frappe/frappe_docker) checkout that has this app added to `apps.json`.

**Build the image:**

```bash
docker build \
  --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
  --build-arg=FRAPPE_BRANCH=version-16 \
  --build-arg=CACHE_BUST="$(date +%s)" \
  --secret=id=apps_json,src=./gitops/apps.json \
  --tag=lukecart/bullwheel:latest \
  --file=images/layered/Containerfile .
```

**Render and start the compose stack:**

```bash
docker compose --project-name bullwheel \
  --env-file ./gitops/bullwheel.env \
  -f compose.yaml \
  -f overrides/compose.mariadb.yaml \
  -f overrides/compose.redis.yaml \
  -f overrides/compose.nginxproxy.yaml \
  -f overrides/compose.nginxproxy-ssl.yaml config > ./gitops/bullwheel.yaml

docker compose --project-name bullwheel -f bullwheel.yaml up -d
```

**Set up the site** (exec into the `bullwheel-backend` container as `root`):

```bash
bench new-site --mariadb-user-host-login-scope=% \
  --db-root-password '<db-root-password>' \
  --admin-password '<admin-password>' \
  <site-name>

bench --site <site-name> install-app bullwheel offsite_backups
bench --site <site-name> build
bench --site <site-name> migrate
bench use <site-name>
```

### Connecting to Ascend's SQL Server

Bullwheel authenticates to Ascend's SQL Server with a dedicated login rather than `sa`. In SQL Server Management Studio, connected via Windows Authentication to the Ascend server:

1. Under **Security > Logins**, create a SQL Server Authentication login named `bullwheel`.
2. Under **Databases > Ascend > Security > Users**, create a user named `bullwheel` (User Type: "SQL user with login", login name `bullwheel`).
3. Grant `bullwheel` `UPDATE` and `INSERT` permissions on `dbo.Products` and `dbo.VendorProducts`.

Store the resulting credentials in a `SQL Server` document in Bullwheel (`bullwheel/database/doctype/sql_server/`) — see [`documentation/MSSQLDatabase.md`](documentation/MSSQLDatabase.md).

## Development

See [`CLAUDE.md`](CLAUDE.md) for the full development context, coding conventions, and architectural notes for this app, and the [`documentation/`](documentation) directory for feature-level guides:

| Doc | Covers |
|---|---|
| [`MSSQLDatabase.md`](documentation/MSSQLDatabase.md) | The SQL Server connection/query handler |
| [`VIRTUAL_DOCTYPE_DEVELOPMENT.md`](documentation/VIRTUAL_DOCTYPE_DEVELOPMENT.md) | Building a new virtual DocType over an Ascend table |
| [`MONKEY_PATCH.md`](documentation/MONKEY_PATCH.md) | The virtual-DocType link-title patch |
| [`RECEIVING_FLOW.md`](documentation/RECEIVING_FLOW.md) | The Order Receipt / vendor product scanning workflow |
| [`LABEL_PRINTING.md`](documentation/LABEL_PRINTING.md) / [`LABEL_PRINTING_REQUIREMENTS.md`](documentation/LABEL_PRINTING_REQUIREMENTS.md) | Zebra ZPL label printing |
| [`DESCRIPTION_TEMPLATES.md`](documentation/DESCRIPTION_TEMPLATES.md) | Jinja-based product description generation |
| [`CLIENT_UTILITIES.md`](documentation/CLIENT_UTILITIES.md) | Shared client-side JS bundle (`bullwheel.*` namespaces) |

A couple of Desk-level settings are expected in development and production sites:

- **System Settings > Password**: disable Password Policy
- **System Settings > Display**: disable Hide Empty Read-Only Fields

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/bullwheel
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

Coding style follows the conventions in [`CLAUDE.md`](CLAUDE.md): descriptive names over acronyms/shorthand, inline documentation on non-trivial methods, parameterized queries only, and context-manager patterns for connection lifecycles.

## Backups

Backups are stored in Google Drive under the store's Bullwheel account. Backups older than 30 days are pruned automatically by a scheduled Apps Script project. Backup destination configuration is managed from the Google Drive settings within Bullwheel.

## License

All Rights Reserved. Copyright (c) 2026 Bonneville Ridge LLC. See [`license.txt`](license.txt). This is proprietary software for internal use by Barrie's Ski and Sports — unauthorized copying or distribution is prohibited.
