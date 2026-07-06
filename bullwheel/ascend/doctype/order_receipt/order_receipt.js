// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on("Order Receipt", {
 	refresh(frm) {
        $(frm.wrapper)
			.off('keydown.scan')
			.on('keydown.scan', '[data-fieldname="add_item"] input', function (event) {
				if (event.key !== 'Enter') return;
				event.preventDefault();

				// Read straight from the input element. A Frappe Data field only
				// syncs into frm.doc on its change event (blur/debounce), which has
				// not fired yet when Enter is pressed mid-typing — so frm.doc.add_item
				// would be stale and the scan would appear to be missed.
				const input = event.target;
				const scanned_value = (input.value || '').trim();
				if (!scanned_value) return;

				// Clear the input immediately so the user can scan the next item
				// without waiting on the server round-trip, and keep the model in sync.
				$(input).val('');
				frm.doc.add_item = '';

				frm.call('scan_item', {id: scanned_value}).then((response) => {
					const [status, record] = response.message || [];

					if (status === 'vpn found') {
						// record is the Vendor Product's docname, e.g. "12345 (Specialized)".
						const vpn = record;
						const existing_row = (frm.doc.order_items || []).find(
							row => row.item_type === 'Vendor Product' && row.vpn === vpn
						);

						if (existing_row) {
							frappe.model.set_value(existing_row.doctype, existing_row.name, 'quantity', existing_row.quantity + 1);
						} else {
							frm.add_child('order_items', {
								item_type: 'Vendor Product',
								vpn: vpn,
								quantity: 1
							});
						}
						frm.refresh_field('order_items');
						frappe.show_alert({
							message: `Added: ${frappe.utils.escape_html(vpn)}`,
							indicator: 'green'
						});
					} else {
						// No Vendor Product on file — stage a New Product entry for review.
						// record (when present) carries the matched Product's UPC; otherwise
						// fall back to whatever was scanned.
						const upc = (record && record.upc) || scanned_value;

						frm.add_child('table_tvbc', {upc: upc});
						frm.refresh_field('table_tvbc');
						frappe.show_alert({
							message: `New product needed for: ${frappe.utils.escape_html(upc)}`,
							indicator: 'orange'
						});
					}
				});
			});
 	},
});
