// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('Label Printer', {
    refresh(frm) {
        const button = frm.add_custom_button(__('Test Connection'), () => {
            frappe.show_alert({ message: __('Testing connection...'), indicator: 'blue' });

            frappe.call({
                method: 'bullwheel.label_printing.test_connection',
                args: { doc: frm.doc },
            });
        });

        button.prop('disabled', frm.is_new());
        frm.test_connection_button = button;
        update_test_connection_button_visibility(frm);
    },

    connection_method(frm) {
        if (frm.test_connection_button) {
            update_test_connection_button_visibility(frm);
        }
    }
});

function update_test_connection_button_visibility(frm) {
    const connection_method = frm.doc.connection_method;
    const button = frm.test_connection_button;

    if (connection_method === 'USB' || connection_method === 'Network') {
        button.show();
    } else {
        button.hide();
    }
}
