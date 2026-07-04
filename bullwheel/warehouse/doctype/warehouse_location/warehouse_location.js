// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Warehouse Location', {
	refresh(frm) {
		frm.add_custom_button(__('Print Label'), () => {
			// Ask which configured Label Printer to send to, since there is no
			// default-printer concept yet. The label layout itself lives in the
			// Zebra Printer Label record configured under Bullwheel Settings ▸
			// Printing ▸ Labels ▸ Warehouse Location; the server renders it.
			frappe.prompt(
				[
					{
						label: __('Printer'),
						fieldname: 'printer',
						fieldtype: 'Link',
						options: 'Label Printer',
						reqd: 1,
					},
				],
				(values) => {
					frappe.show_alert({ message: __('Sending label...'), indicator: 'blue' });
					frappe.call({
						method: 'bullwheel.label_printing.doctype.label_printer.label_printer.print_label',
						args: {
							printer_name: values.printer,
							slot: 'warehouse_location',
							doctype: 'Warehouse Location',
							docname: frm.doc.name,
						},
						callback() {
							frappe.show_alert({ message: __('Label sent'), indicator: 'green' });
						},
					});
				},
				__('Print Label'),
				__('Print')
			);
		});

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
								// Preview values for description and upc will be replaced after save by virtual field implementation.
								product: store_upc,
								description: product["Description"],
								upc: product["UPC"],
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
