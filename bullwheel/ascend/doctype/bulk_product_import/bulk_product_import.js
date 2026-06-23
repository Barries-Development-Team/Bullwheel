// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Bulk Product Import', {
    refresh(frm) {
        frm.add_custom_button(__('Generate Import Sheet'), () => {
            //frappe.show_alert({ message: __('Generating sheet...'), indicator: 'blue' });
            frappe.show_alert({ message: __('This feature is not implemented yet :('), indicator: 'blue' });

            frappe.call({
                method: 'bullwheel.ascend.doctype.bulk_product_import.bulk_product_import.generate_import_sheet',
                args: { doc: frm.doc },
            });
        });
    }
});

// 	},
// });
