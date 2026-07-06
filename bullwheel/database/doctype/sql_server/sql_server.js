// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.ui.form.on('SQL Server', {
    refresh(frm) {
        const button = frm.add_custom_button(__('Test Connection'), () => {
            frappe.show_alert({ message: __('Testing connection...'), indicator: 'blue' });

            frappe.call({
                method: 'bullwheel.database.doctype.sql_server.sql_server.test_connection',
                args: { doc: frm.doc },
            });
        });

        button.prop('disabled', frm.is_new());
    }
});

// 	},
// });
