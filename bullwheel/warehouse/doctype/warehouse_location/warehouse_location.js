// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Resolve a scanned identifier to a product — an Ascend Product, or a New Product still waiting
// to be imported into Ascend — and add/increment its inventory row.
function handle_scan(frm, scanned_value) {
	frappe.call({
		method: 'bullwheel.ascend.product_lookup.resolve_scanned_product',
		args: {identifier: scanned_value},
		callback(response) {
			const product = response.message;
			// null when no product matches the scan.
			if (!product) {
				frappe.show_alert({
					message: `No product found for: ${frappe.utils.escape_html(scanned_value)}`,
					indicator: 'red'
				});
				return;
			}

			// The Dynamic Link stores the product's name (the Store SKU or New Product name),
			// not the scanned barcode.
			const existing_row = (frm.doc.location_inventory_quantities || []).find(
				row => row.product === product.name && row.product_type === product.doctype
			);

			if (existing_row) {
				frappe.model.set_value(existing_row.doctype, existing_row.name, 'quantity', existing_row.quantity + 1);
			} else {
				frm.add_child('location_inventory_quantities', {
					// Preview values for description and upc will be replaced after save by virtual field implementation.
					product_type: product.doctype,
					product: product.name,
					description: product.description,
					upc: product.upc,
					quantity: 1
				});
			}
			frm.refresh_field('location_inventory_quantities');
			frappe.show_alert({
				message: `Added: ${frappe.utils.escape_html(product.description || product.name)}`,
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
		bullwheel.printing.add_print_button({
			frm: frm,
			label: 'Print Label',
			slot: 'warehouse_location',
		});

		setup_scan_box(frm);
	}
});
