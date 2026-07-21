# Changelog

All notable changes to Bullwheel are recorded here. Grouped by version.

## [1.0.1] - July 20, 2026

### Bug Fix

- Fixed `_check_autoname_safety` not reloading DocType config from JSON during `bench migrate`, causing a migrate failure.

## [1.0.0] - July 20, 2026

### Features

- Bullwheel can now edit Ascend data.
- New Order Receipt builder for easy, single-pass, receiving of large retail and demo gear orders!
- Items can now be checked in and out of Warehouse Location bays.
- Added batch printing for labels. Additionally, labels can also now be printed for vendor products.
- Added Product Description Templates.
- The last selected label printer will now be remembered, per user.``
- Improved Ascend Virtual DocType filter support.
- Added database traffic encryption for improved security.
- Added new job-based editing system for simultaneous document editing.
- Reorganized numerous UI layouts.
- Made default ZPL designs read-only to prevent accident edits.

### Framework Updated

- Updated to Frappe Framework 16.27.1 from 16.26.3 ([Release Notes](https://github.com/frappe/frappe/releases#release-v16.27.1))

### Performance

- Improved caching of Order Item details to significantly reduce redundant Ascend SQL Server queries.

### Bug Fixes

- Fixed issue where scanned barcodes could be saved to a Warehouse Location document scan field.
- Data Import tool now correctly resolves UPCs when importing from a `xlsx` file.
- Fixed Virtual DocType search fields not being displayed in Link field search.
- Fixed UPC display for Order Receipt Items.

## [0.0.8] - July 10, 2026

### Features

- Added an "Open Warehouse Bay" shortcut to the Warehouse Workspace for easy scanning and access of individual warehouse locations.
- Added some fancy new icons!

### Bug Fixes

- Fix numerous major backend bugs related to Ascend Virtual Doctypes.

## [0.0.7] - July 9, 2026

### Features

- Added dynamic font resizing and wrap-around for long Model names on Swap Tags.
- Products can now be searched by both Ascend SKU and UPC in the ID field in List View.
- Ascend Virtual DocTypes can now be retrieved by any number of set fields, in addition to the "name" field.
- Product Swap and Online Pricing can now be updated in bulk via the Data Import tool.
- Swap and Online pricing history for a Product can now be viewed from the respective Product Price form.

### Bug Fixes

- Fixed Swap Tags printing MSRP for the price instead of the swap price.


## [0.0.6] - July 8, 2026

### Features

- Implemented Ascend, Bullwheel, and Warehouse Workspaces.
- Added Desktop icons for easy Workspace access.

### Bug Fixes

- Fixed Server Error resulting from missing parameter when retrieving Ascend record count.

## [0.0.5] - July 6, 2026

- Reordered Ascend Product layout, added fields for swap and online pricing, changed new product naming, and created the Product Price DocType.
- Updated Bullwheel settings to include a default online tag.
- Added the "Print Label" button group to Ascend Product.
- Test Connection buttons are now hidden on new, unsaved forms for SQL Server and Label Printer connections.
- Permitted Warehouse Location Group status changes.
- Added Swap/Online price edit functionality.
- Added Ascend Product Tag fixture.
- Added product detail display fields to the Ski with Bindings DocType.
- Implemented order receipt item scanning.
