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
	}
});
