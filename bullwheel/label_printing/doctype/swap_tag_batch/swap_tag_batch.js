// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Resolve a scanned identifier to an Ascend Product and add/increment its inventory row.
function handle_scan(frm, scanned_value) {
	frappe.call({
		method: 'bullwheel.ascend.doctype.ascend_product.ascend_product.get_values',
		args: {name: scanned_value, fields: ['name', 'description', 'upc']},
		callback(response) {
			const product = response.message;
			// get_values returns the product record (truthy object) when found,
			// or null when no product matches the scan.
			if (!product) {
				frappe.show_alert({
					message: `No product found for: ${frappe.utils.escape_html(scanned_value)}`,
					indicator: 'red'
				});
				return;
			}

			// The Link field stores the Ascend Product's name (the ID column),
			// not the scanned barcode.
			const store_upc = product.name;
			const existing_row = (frm.doc.swap_tag_items || []).find(
				row => row.product === store_upc
			);

			if (existing_row) {
				frappe.model.set_value(existing_row.doctype, existing_row.name, 'print_quantity', existing_row.print_quantity + 1);
			} else {
				frm.add_child('swap_tag_items', {
					// Preview values for description and upc will be replaced after save by virtual field implementation.
					print: 1,
                    product: store_upc,
					description: product.description,
					print_quantity: 1
				});
			}
			frm.refresh_field('swap_tag_items');
			frappe.show_alert({
				message: `Added: ${frappe.utils.escape_html(product.description || store_upc)}`,
				indicator: 'green'
			});
		}
	});
}

// Mount the scan box as a standalone control (no frm/doc) inside the scan_here HTML field, so
// typing/scanning never writes to frm.doc. Frappe re-renders the HTML field on every form
// refresh, so we re-mount the control here each time.
function setup_scan_box(frm) {
	const field = frm.get_field('scan_here');
	if (!field) return;

	field.$wrapper.empty();
	const control = frappe.ui.form.make_control({
		df: {
			fieldtype: 'Data',
			fieldname: 'scan_here',
			label: __('Add Item'),
			options: 'Barcode',
			placeholder: __('Scan here')
		},
		parent: field.$wrapper,
		render_input: true
	});
	control.refresh();

	// Read/clear the raw input directly; the value stays out of frm.doc entirely.
	control.$input.on('keydown', (event) => {
		if (event.key !== 'Enter') return;
		event.preventDefault();

		const scanned_value = (control.$input.val() || '').trim();
		if (!scanned_value) return;

		control.$input.val('');
		handle_scan(frm, scanned_value);
	});
}

frappe.ui.form.on('Swap Tag Batch', {
	refresh(frm) {
        frm.add_custom_button(__('Print Enabled Labels'), function() {

            let count = (frm.doc.swap_tag_items || []).reduce((total, row) => total + (row.print_quantity || 0), 0);

            frappe.confirm(`You are about to print ${count} labels. Proceed?`,
                // Yes
                () => {},
                // No
                () => { return; })


            // TODO: Print logic
        });


		setup_scan_box(frm);
	}
});
