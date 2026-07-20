// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Vendor Product', {
	refresh(frm) {
		// Vendor Product is a Resolved doctype: the server follows its `product` link
		// to the Ascend Product before rendering, so no doctype/items are passed here.
		bullwheel.printing.add_print_button({ frm: frm, label: 'Print Swap Tag', slot: 'swap_tag' });
		bullwheel.printing.add_print_button({ frm: frm, label: 'Print Ascend Tag', slot: 'ascend_tag' });
		bullwheel.printing.add_print_button({ frm: frm, label: 'Print Online Tag', slot: 'online_tag' });
	},
});
