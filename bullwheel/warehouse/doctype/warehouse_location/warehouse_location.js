// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Warehouse Location', {
	refresh(frm) {
		$(frm.wrapper)
			.off('keydown.scan')
			.on('keydown.scan', '[data-fieldname="scan_here"] input', function (event) {
				if (event.key !== 'Enter') return;
				event.preventDefault();

				const scanned_value = (frm.doc.scan_here || '').trim();
				if (!scanned_value) return;

				frappe.call({
					method: 'frappe.desk.search.search_link',
					args: {
						txt: scanned_value,
						doctype: 'Ascend Product',
						ignore_user_permissions: 0,
						reference_doctype: 'Location Inventory',
						query: 'bullwheel.ascend.doctype.ascend_product.ascend_product.ascend_product_search',
						page_length: 1
					},
					callback(response) {
						const results = response.results || [];
						if (!results.length) {
							frappe.show_alert({
								message: `No product found for: ${frappe.utils.escape_html(scanned_value)}`,
								indicator: 'red'
							});
						} else {
							frm.add_child('location_inventory_quantities', {
								product: results[0].value,
								quantity: 1
							});
							frm.refresh_field('location_inventory_quantities');
							frappe.show_alert({
								message: `Added: ${results[0].description || results[0].value}`,
								indicator: 'green'
							});
						}
						frm.set_value('scan_here', '');
					}
				});
			});
	}
});
