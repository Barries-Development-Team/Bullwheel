// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Ascend Product', {
	refresh(frm) {
		const print_label_group = __('Print Labels');

		const add_print_button = (button_label, slot) => {
			frm.add_custom_button(__(button_label), () => {
				// Ask which configured Label Printer to send to, since there is no
				// default-printer concept yet. The tag layout itself lives in the
				// Zebra Printer Label record configured under Bullwheel Settings ▸
				// Printing ▸ Labels; the server renders it.
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
						frappe.show_alert({ message: __('Sending {0}...', [button_label]), indicator: 'blue' });
						frappe.call({
							method: 'bullwheel.label_printing.doctype.label_printer.label_printer.print_label',
							args: {
								printer_name: values.printer,
								slot: slot,
								doctype: 'Ascend Product',
								docname: frm.doc.name,
							},
							callback() {
								frappe.show_alert({ message: __('{0} sent', [button_label]), indicator: 'green' });
							},
						});
					},
					__(button_label),
					__('Print')
				);
			}, print_label_group);
		};

		add_print_button('Print Swap Tag', 'swap_tag');
		add_print_button('Print Ascend Tag', 'ascend_tag');
		add_print_button('Print Online Tag', 'online_tag');
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
