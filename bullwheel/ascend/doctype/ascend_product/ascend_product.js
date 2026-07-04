// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Ascend Product', {
	refresh(frm) {
		frm.add_custom_button(__('Print Swap Tag'), () => {
			// Ask which configured Label Printer to send to, since there is no
			// default-printer concept yet. The tag layout itself lives in the
			// Zebra Printer Label record configured under Bullwheel Settings ▸
			// Printing ▸ Labels ▸ Swap Tag; the server renders it.
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
					frappe.show_alert({ message: __('Sending swap tag...'), indicator: 'blue' });
					frappe.call({
						method: 'bullwheel.label_printing.doctype.label_printer.label_printer.print_label',
						args: {
							printer_name: values.printer,
							slot: 'swap_tag',
							doctype: 'Ascend Product',
							docname: frm.doc.name,
						},
						callback() {
							frappe.show_alert({ message: __('Swap tag sent'), indicator: 'green' });
						},
					});
				},
				__('Print Swap Tag'),
				__('Print')
			);
		});
	}
});
