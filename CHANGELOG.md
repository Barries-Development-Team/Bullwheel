# Changelog

All notable changes to Bullwheel are recorded here. Grouped by version.

## [1.1.6] - August 5, 2026

### Bug Fixes

- Fixed exported import sheets carrying the blank sample rows their template ships with, which Ascend imported as phantom order lines and which inflated the item count shown for an order. A generated sheet now ends at its last real row.
- Vendor Products created by Bullwheel during receiving are now attributed to the acting user's Ascend User, like every other Ascend record. Previously they were written with no Creator, which could later block the order that referenced them from saving.

## [1.1.5] - August 4, 2026

### Features

- Added the Ascend User DocType.
- Users can now be linked to a corresponding Ascend User via a new "Ascend User" field, with a configurable default fallback in Bullwheel Settings for users without one.
- Edits to Ascend records are now attributed to the acting user's linked Ascend User (falling back to the configured default) instead of leaving Creator/Modifier fields unset.

### Bug Fixes

- Fixed a crash searching the Ascend User Link field, caused by records with a blank Employee ID.

## [1.1.4] - August 3, 2026

### Performance Improvements

- Implemented Redis caching of static and long-lived Ascend SQL Server data.
- Cached SQL Server configuration information for faster sequential database connections.

### Bug Fixes

- Fixed Order Receipt Item Description and Barcode fields not refreshing by, you guessed it, better caching.
- Fixed incorrect whitelisted function reference preventing item location bays from being fetched during check-out.

## [1.1.3] - July 31, 2026

### Features

- Added a "Open Product" button to the Order Receipt form view.
- Implemented an improved Add Order Item flow.

### Changes

- Vendor Product now displays UPC.
- Made Vendor Product searchable by UPC and Store SKU.
- Order Receipt Item actions are now grouped.

### Bugfixes

- Fixed "cm" being included on improper Description Templates.
- Fixed Ascend Tag descriptions printing over barcodes.
- Fixed Ascent Tag element alignment.

### Known Issues

- Description and UPC columns in Order Receipt Item table don't update when the corresponding value is changed.

## [1.1.2] - July 27, 2026

### Changes

- Removed Cost autofill on linked Vendor Prodcut.
- Made the Vendor Product link on the Edit Order Item dialog read-only.
- Scanning an item into an order no longer increments received rows.

## [1.1.1] - July 24, 2026

### Bug Fixes

- Removed multi-product location dialog, restoring full Find Product functionality.
- Fixed default Ascend Tag description truncation.

## [1.1.0] - July 24, 2026

### Features

- Overhauled the process of finding products in Warehouse Locations.
    - Replaced the Find Product page with a dialog prompt.
    - Added Find Product buttons to Ascend Products.
    - Added multi-product location finding support.
- Added a New Product creation dialog, replacing the previous workflow, with Quick Entry support for key fields including Gender.
- Added a Vendor Part Number (VPN) generator for New Product, including a configurable VPN prefix, uniqueness checks, and a varchar-limit safety check.
- New Product now automatically generates Swap and Online Product Pricing on save, with pricing rule validation.
- Added the Product Pricing Rule DocType.
- Added a confirmation prompt before saving a New Product.
- Order Receipt now caches the resolved Vendor ID and supports scanning items with a VPN Prefix.
- Virtual DocType JOIN-sourced fields (such as Ascend Product category) can now be edited and saved.

### Bug Fixes

- Fixed UI element updates (such as Workspaces and Desktop Icons) and Roles not being applied on app update.
- Fixed `NewProduct.validate` crash when the UPC field was blank.
- Fixed an off-by-one error in UPC length validation that rejected valid 20-character UPCs.
- Fixed virtual-doctype id resolution wiping the linked foreign key on unrelated saves.
- Fixed silent, arbitrary category assignment on ambiguous (non-unique) category names; the save is now aborted with a clear error instead.
- Fixed `OrderReceipt.subtotal`/`total_order_items` crash when a scanned item's cost or quantity was `None`.
- Guarded `NewProduct.after_insert` VPN lookup so a missing just-created Ascend Product throws a clear error instead of a `TypeError`.
- Fixed a bug allowing New Product to be saved twice.
- Fixed Vendor field visibility and display bugs, and a related reload bug, on New Product.
- Fixed a breadcrumbs display bug.
- Made Category, Brand, and Style Name mandatory on New Product, and made Ski binding data optional (no longer required) for Ski with Bindings.
- Temporarily disabled the Add Order Item button.

### Chores

- Regenerated fixtures, including removal of Workspace and Workspace-related DocType fixtures.

## [1.0.2] - July 20, 2026

### Bug Fixes

- Fixed Data Import failing to verify Ascend Products when the UPC contains uppercase letters.
- Applied temporary hotfix to correct get_list only retrieving 20 items for Virtual DocTypes.

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
