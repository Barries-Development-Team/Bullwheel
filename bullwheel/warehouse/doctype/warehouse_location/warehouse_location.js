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
			const existing_row = (frm.doc.location_inventory_quantities || []).find(
				row => row.product === store_upc
			);

			if (existing_row) {
				frappe.model.set_value(existing_row.doctype, existing_row.name, 'quantity', existing_row.quantity + 1);
			} else {
				frm.add_child('location_inventory_quantities', {
					// Preview values for description and upc will be replaced after save by virtual field implementation.
					product: store_upc,
					description: product.description,
					upc: product.upc,
					quantity: 1
				});
			}
			frm.refresh_field('location_inventory_quantities');
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

		setup_scan_box(frm);
	}
});
