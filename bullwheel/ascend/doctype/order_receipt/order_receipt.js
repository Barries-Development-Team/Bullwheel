// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on("Order Receipt", {
 	refresh(frm) {

		if (!frm.is_new()) {
			frm.add_custom_button("Add Item", () => {
            	// Your logic here
            	frappe.msgprint("Button clicked!");
			});
			frm.add_custom_button("Edit Item", () => {
				// Your logic here
				frappe.msgprint("Button clicked!");
			});
			frm.add_custom_button("Remove Item", () => {
				// Your logic here
				frappe.msgprint("Button clicked!");
			});
		}
		

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

				frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.scan_item', {
					id: scanned_value,
					vendor: frm.doc.vendor
				}).then((response) => {
					const [status, record] = response.message || [];

					if (status === 'vpn found') {
						// record.vpn is the Vendor Product's docname, e.g. "12345 (Specialized)".
						const existing_row = (frm.doc.order_items || []).find(
							row => row.item_type === 'Vendor Product' && row.vpn === record.vpn
						);

						if (existing_row) {
							frappe.model.set_value(existing_row.doctype, existing_row.name, 'quantity', existing_row.quantity + 1);
						} else {
							frm.add_child('order_items', {
								item_type: 'Vendor Product',
								vpn: record.vpn,
								description: record.description,
								upc: record.upc,
								quantity: 1,
								cost: record.cost
							});
						}
						frm.refresh_field('order_items');
						frappe.show_alert({
							message: `Added: ${frappe.utils.escape_html(record.vpn)}`,
							indicator: 'green'
						});
					} else if (status === 'product found') {
						// Ascend has this product, but this vendor has no Vendor Product
						// on file for it yet — stage a New Product entry to record the
						// new vendor association.
						stage_new_product(frm, {
							upc: record.upc,
							description: record.description,
							comments: 'Existing product receiving a new vendor product association.'
						});
					} else {
						// No record of this item anywhere — confirm before creating one from scratch.
						frappe.confirm(
							`No product found for "${frappe.utils.escape_html(scanned_value)}". Create a new product record?`,
							() => stage_new_product(frm, {
								upc: scanned_value,
								description: null,
								comments: 'New product — no existing record found.'
							})
						);
					}
				});
			});
 	},
});

function stage_new_product(frm, {upc, description, comments}) {
	// Every "New Product" entry needs a placeholder VPN since it has no
	// Vendor Product on file yet; the real one is filled in during review.
	const new_product_row = frm.add_child('new_products', {
		vpn: frappe.utils.get_random(10),
		upc: upc,
		description: description
	});
	frm.refresh_field('new_products');

	// Link the order item back to the New Product row we just staged.
	frm.add_child('order_items', {
		item_type: 'New Product',
		vpn: new_product_row.name,
		quantity: 1,
		comments: comments
	});
	frm.refresh_field('order_items');

	frappe.show_alert({
		message: `New product staged for: ${frappe.utils.escape_html(upc)}`,
		indicator: 'orange'
	});
}
