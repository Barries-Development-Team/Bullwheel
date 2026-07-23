// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Ascend Product', {
	refresh(frm) {
		bullwheel.printing.add_print_button({ frm, label: 'Print Swap Tag', slot: 'swap_tag' });
		bullwheel.printing.add_print_button({ frm, label: 'Print Ascend Tag', slot: 'ascend_tag' });
		bullwheel.printing.add_print_button({ frm, label: 'Print Online Tag', slot: 'online_tag' });

		frm.add_custom_button(__('Check In'), () => {
			bullwheel.warehouse.check_in_item({ product: frm.doc.name });
		}, __('Check In/Out'));

		frm.add_custom_button(__('Check Out'), () => {
			bullwheel.warehouse.check_out_item({ product: frm.doc.name });
		}, __('Check In/Out'));

		frm.add_custom_button(__('Find Product'), () => {
			bullwheel.warehouse.product_location_dialog({
				product_sku: frm.doc.name, 
				description: frm.doc.description
			})
		});
	},

	edit_swap_price(frm) {
		edit_product_price(frm, 'SWAP', 'Ski Swap Price', __('Edit Swap Price'));
	},

	edit_online_price(frm) {
		edit_product_price(frm, 'ONLINE', 'Online Listing Price', __('Edit Online Price'));
	},
});

function edit_product_price(frm, type, pricing_type, dialog_title) {
	// Product Price names are deterministic (PRICE-<TYPE>-<product>, set in
	// ProductPrice.autoname), so we can check for an existing record and
	// pre-fill its price before deciding whether to update or create one —
	// all without leaving the Ascend Product form.
	const price_name = `PRICE-${type}-${frm.doc.name}`;

	const open_prompt = (default_price, exists) => {
		frappe.prompt(
			[
				{
					fieldname: 'price',
					fieldtype: 'Currency',
					label: __('Price'),
					reqd: 1,
					default: default_price,
				},
			],
			(values) => {
				const save = exists
					? frappe.db.set_value('Product Price', price_name, 'price', values.price)
					: frappe.db.insert({
							doctype: 'Product Price',
							product: frm.doc.name,
							pricing_type: pricing_type,
							price: values.price,
					  });

				save.then(() => {
					frappe.show_alert({ message: __('Price saved'), indicator: 'green' });
					frm.reload_doc();
				});
			},
			dialog_title,
			__('Save')
		);
	};

	frappe.db.exists('Product Price', price_name).then((exists) => {
		if (exists) {
			frappe.db.get_value('Product Price', price_name, 'price').then((r) => {
				open_prompt(r.message.price, true);
			});
		} else {
			open_prompt(undefined, false);
		}
	});
}