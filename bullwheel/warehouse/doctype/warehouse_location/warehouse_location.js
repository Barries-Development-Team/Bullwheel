// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Warehouse Location', {
	refresh(frm) {
		frm.add_custom_button(__('Print Label'), () => {
			// Ask which configured Label Printer to send to, since there is no
			// default-printer concept yet. Replace the ZPL below with the real
			// label layout once the label design is finalized.
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
					// The label geometry is measured in dots, so the printer's DPI
					// must be known as a number before the ZPL is built (ZPL cannot
					// do arithmetic). Fetch it from the selected Label Printer, then
					// build and send the label.
					frappe.db.get_value('Label Printer', values.printer, 'dpi').then((response) => {
						const dpi = response.message.dpi || 203;
						const label_width = 2 * dpi; // 2" label width in dots

						// --- EXAMPLE ZPL — replace with the real label layout ---
						const location_name = (frm.doc.name || '').replace(/[\^~]/g, ' ');

						// ^FB<width>,1,0,C centers TEXT fields, but it does NOT move a
						// barcode's bars — those always start at the ^FO origin. So the
						// barcode is centered manually from its computed width instead.
						const module_width = 2; // ^BY narrow-bar width in dots
						// Code 128 width ≈ (11 * chars + 35) modules: start + data +
						// checksum + stop. Assumes subset B (worst case); the encoder
						// may compress all-numeric data and render slightly narrower.
						const barcode_width = (11 * location_name.length + 35) * module_width;
						const barcode_x = Math.max(0, Math.floor((label_width - barcode_width) / 2));

						const zpl = [
							'^XA',
							`^PW${label_width}`,
							`^FO0,20^FB${label_width},1,0,C^A0N,30,30^FDBarrie's Warehouse^FS`,
							`^FO0,60^FB${label_width},1,0,C^A0N,40,40^FDLocation: ${location_name}^FS`,
							`^FO${barcode_x},110^BY${module_width}^BCN,80,N,N,N^FD${location_name}^FS`,
							'^XZ',
						].join('');
						// --------------------------------------------------------

						frappe.show_alert({ message: __('Sending label...'), indicator: 'blue' });
						frappe.call({
							method: 'bullwheel.label_printing.doctype.label_printer.label_printer.print_zpl',
							args: { printer_name: values.printer, zpl: zpl },
							callback() {
								frappe.show_alert({ message: __('Label sent'), indicator: 'green' });
							},
						});
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
