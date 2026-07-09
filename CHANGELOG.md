# Changelog

All notable changes to Bullwheel are recorded here. Grouped by version.

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
