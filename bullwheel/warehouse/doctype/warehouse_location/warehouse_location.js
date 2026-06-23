// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Warehouse Location', {
	refresh(frm) {
		$(frm.wrapper)
			.off('keydown.scan')
			.on('keydown.scan', '[data-fieldname="scan_here"] input', function (event) {
				if (event.key !== 'Enter') return;
				event.preventDefault();

				// Read straight from the input element. A Frappe Data field only
				// syncs into frm.doc on its change event (blur/debounce), which has
				// not fired yet when Enter is pressed mid-typing — so frm.doc.scan_here
				// would be stale and the scan would appear to be missed.
				const input = event.target;
				const scanned_value = (input.value || '').trim();
				if (!scanned_value) return;

				// Clear the input immediately so the user can scan the next item
				// without waiting on the server round-trip, and keep the model in sync.
				$(input).val('');
				frm.doc.scan_here = '';

				frappe.call({
					method: 'bullwheel.ascend.doctype.ascend_product.ascend_product.get_product_dict',
					args: {id: scanned_value, type: 'summary'},
					callback(response) {
						const product = response.message;
						// get_product_dict returns the product record (truthy object)
						// when found, or null when no product matches the scan.
						if (!product) {
							frappe.show_alert({
								message: `No product found for: ${frappe.utils.escape_html(scanned_value)}`,
								indicator: 'red'
							});
							return;
						}

						// The Link field stores the Ascend Product's name (the ID
						// column), not the scanned barcode.
						const store_upc = product["Store UPC"];
						const existing_row = (frm.doc.location_inventory_quantities || []).find(
							row => row.product === store_upc
						);

						if (existing_row) {
							frappe.model.set_value(existing_row.doctype, existing_row.name, 'quantity', existing_row.quantity + 1);
						} else {
							frm.add_child('location_inventory_quantities', {
								product: store_upc,
								quantity: 1
							});
						}
						frm.refresh_field('location_inventory_quantities');
						frappe.show_alert({
							message: `Added: ${frappe.utils.escape_html(product.Description || product["Store UPC"])}`,
							indicator: 'green'
						});
					}
				});
			});
	}
});
